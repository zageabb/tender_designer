from __future__ import annotations

from research_core import (
    CoverageAssessment,
    DynamicResearchConfig,
    DynamicResearchController,
    OperationResult,
    RankingConfig,
    ResearchEngine,
    __version__ as research_core_version,
    rank_candidates,
)
from research_core.ranking import normalise_url


def install_research_core_equipment() -> None:
    """Use research-core for Tender Designer's equipment research lifecycle.

    Tender Designer still owns its prompts, search providers, procurement index,
    page reader, source-review rules and final compliance QA. research-core owns
    candidate ranking, batching, stagnation and stop/continue lifecycle.
    """
    import services.equipment_research_agent as equipment

    agent_class = equipment.EquipmentResearchAgent
    if getattr(agent_class, "_research_core_v01_installed", False):
        equipment.install_equipment_research()
        return

    original_research = agent_class.research

    def core_rank_candidates(
        self,
        candidates,
        clarified_specification: str,
        requirements: dict,
        evidence_questions: list[str],
    ):
        if len(candidates) < 2:
            return candidates, []

        target_text = " ".join([
            clarified_specification,
            equipment._flatten_requirements(requirements),
            " ".join(evidence_questions),
        ])
        # Keep Tender Designer's domain-specific stop-word treatment while the
        # common core owns scoring and source diversity.
        core_target = " ".join(sorted(equipment._meaningful_terms(target_text))) or target_text
        config = RankingConfig(max_per_domain=3, embedding_shortlist=60)
        diagnostics: list[str] = []

        ranked = rank_candidates(
            candidates,
            core_target,
            title=lambda item: item.title,
            snippet=lambda item: item.snippet,
            url=lambda item: item.url,
            query=lambda item: item.query,
            evidence_signals=tuple(equipment.EVIDENCE_SIGNAL_TERMS),
            weak_signals=tuple(equipment.WEAK_SOURCE_TERMS),
            config=config,
        )

        embedding_model = str(equipment.get_setting("embedding_model", "") or "").strip()
        if embedding_model and len(ranked) >= 2:
            try:
                shortlist = ranked[: config.embedding_shortlist]
                texts = [target_text[:10000]] + [
                    f"{item.title}\n{item.snippet}\nFound via: {item.query}"[:10000]
                    for item in shortlist
                ]
                vectors = self.client.embed_texts(embedding_model, texts)
                if len(vectors) == len(texts):
                    embedding_vectors = {
                        normalise_url(item.url): vector
                        for item, vector in zip(shortlist, vectors[1:])
                    }
                    ranked = rank_candidates(
                        candidates,
                        core_target,
                        title=lambda item: item.title,
                        snippet=lambda item: item.snippet,
                        url=lambda item: item.url,
                        query=lambda item: item.query,
                        target_vector=vectors[0],
                        embedding_vectors=embedding_vectors,
                        evidence_signals=tuple(equipment.EVIDENCE_SIGNAL_TERMS),
                        weak_signals=tuple(equipment.WEAK_SOURCE_TERMS),
                        config=config,
                    )
                    diagnostics.append(
                        f"research-core semantically reranked {len(shortlist)} candidate result(s) with {embedding_model}."
                    )
            except Exception as exc:
                diagnostics.append(
                    "research-core embedding rerank was unavailable; lexical/authority ranking was used instead: "
                    f"{type(exc).__name__}: {exc}"
                )

        diagnostics.append(f"research-core ranked {len(ranked)} candidate URL(s) before page reading.")
        return ranked, diagnostics

    def core_research(self, specification: str, market: str, current_date: str) -> dict:
        if self.answer_prompt_key == "general_search_answer":
            return original_research(self, specification, market, current_date)

        queries, requirements, planning_step = self._plan(specification, market)
        clarified = self._clarified_specification or specification.strip()
        self.progress_callback({
            "kind": "phase",
            "status": "returned",
            "label": planning_step,
            "phase": "Searching",
        })
        self.progress_callback({
            "kind": "reasoning",
            "status": "summary",
            "label": "Clarified technical search request",
            "detail": clarified[:1000],
        })
        if self._evidence_questions:
            self.progress_callback({
                "kind": "reasoning",
                "status": "summary",
                "label": "Evidence questions",
                "detail": "; ".join(self._evidence_questions)[:1000],
            })

        automatic = equipment._setting_mode("equipment_research_depth_mode", "auto") == "auto"
        if automatic:
            depth_config = DynamicResearchConfig(
                initial_batch=equipment._setting_int("equipment_research_initial_pages", 8, 2, 40),
                later_batch=equipment._setting_int("equipment_research_batch_pages", 6, 2, 30),
                hard_page_cap=equipment._setting_int("equipment_research_hard_page_cap", 200, 20, 250),
                hard_round_cap=equipment._setting_int("equipment_research_hard_round_cap", 8, 2, 10),
                stagnant_round_limit=2,
            )
        else:
            depth_config = DynamicResearchConfig(
                initial_batch=self.max_pages,
                later_batch=self.max_pages,
                hard_page_cap=self.max_pages,
                hard_round_cap=self.max_rounds,
                stagnant_round_limit=2,
            )

        engine = ResearchEngine(DynamicResearchController(depth_config))

        def search_callback(active_queries: list[str], seen_urls: set[str]):
            items, diagnostics = self._search_round(active_queries, seen_urls)
            return OperationResult(items=items, diagnostics=diagnostics)

        def rank_callback(candidates, _target_text: str):
            items, diagnostics = self._rank_candidates(
                candidates,
                clarified,
                requirements,
                self._evidence_questions,
            )
            return OperationResult(items=items, diagnostics=diagnostics)

        def read_callback(batch, next_source_id: int):
            items, diagnostics = self._read_pages(batch, next_source_id)
            return OperationResult(items=items, diagnostics=diagnostics)

        def review_callback(opened):
            items, diagnostics = self._review_evidence_sources(
                specification,
                clarified,
                requirements,
                opened,
            )
            return OperationResult(items=items, diagnostics=diagnostics)

        def assess_callback(evidence):
            if not evidence:
                return CoverageAssessment(
                    complete=False,
                    follow_up_queries=[],
                    summary="No useful evidence retained yet; unread ranked candidates will be tried before stopping.",
                )
            follow_up_queries, complete, summary = self._assess_and_refine(
                specification,
                requirements,
                evidence,
                market,
            )
            return CoverageAssessment(
                complete=complete,
                follow_up_queries=follow_up_queries,
                summary=summary,
            )

        def progress_callback(event: dict) -> None:
            if event.get("kind") == "phase":
                round_number = int(event.get("round") or 1)
                self.progress_callback({
                    "kind": "phase",
                    "status": "running",
                    "label": f"Research round {round_number} started",
                    "phase": f"Searching — round {round_number}",
                })
            elif event.get("kind") == "round":
                round_number = int(event.get("round") or 1)
                detail = str(event.get("summary") or "")
                assessment = str(event.get("assessment") or "")
                if assessment:
                    detail += f" {assessment}"
                self.progress_callback({
                    "kind": "reasoning",
                    "status": "summary",
                    "label": f"Round {round_number} evidence summary",
                    "detail": detail[:1000],
                })

        run = engine.run(
            initial_queries=queries,
            target_text=clarified,
            search=search_callback,
            rank=rank_callback,
            read=read_callback,
            review=review_callback,
            assess=assess_callback,
            candidate_key=lambda item: normalise_url(item.url),
            progress=progress_callback,
        )
        evidence = run.evidence

        self.progress_callback({
            "kind": "reasoning",
            "status": "summary",
            "label": "Why research stopped",
            "detail": run.stop_reason,
        })
        if not evidence:
            raise ValueError("The research agent found no useful readable equipment evidence.")

        self.progress_callback({
            "kind": "phase",
            "status": "running",
            "label": f"Synthesising recommendation from {len(evidence)} reviewed sources",
            "phase": "Producing recommendation",
        })
        answer = self._synthesise_equipment(
            specification,
            clarified,
            requirements,
            evidence,
            market,
            current_date,
        )
        answer, qa_diagnostics = self._review_final_answer(
            specification,
            clarified,
            requirements,
            evidence,
            answer,
        )
        diagnostics = [*run.diagnostics, *qa_diagnostics]
        answer, invalid_citations = equipment._validate_citations(answer, evidence)
        if invalid_citations:
            diagnostics.append(
                "Removed unsupported citation identifiers: "
                + ", ".join(f"[{source_id}]" for source_id in sorted(invalid_citations))
            )

        return {
            "answer": answer,
            "sources": [
                {
                    "title": item.title,
                    "url": item.url,
                    "source_id": item.source_id,
                    "quality": self._source_quality.get(item.source_id, "unreviewed"),
                }
                for item in evidence
            ],
            "steps": [
                f"Ollama research model: {self.model}",
                f"Research Core: v{research_core_version}",
                f"Research depth: {'automatic' if automatic else 'manual'}; {run.pages_attempted} page attempt(s).",
                planning_step,
                *run.steps,
                run.stop_reason,
                *diagnostics,
            ],
        }

    agent_class._rank_candidates = core_rank_candidates
    agent_class.research = core_research
    agent_class._research_core_v01_installed = True
    equipment.install_equipment_research()
