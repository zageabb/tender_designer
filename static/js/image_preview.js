(() => {
  const modalElement = document.getElementById("image-preview-modal");
  if (!modalElement) return;

  const modal = bootstrap.Modal.getOrCreateInstance(modalElement);
  const image = document.getElementById("image-preview-content");
  const title = document.getElementById("image-preview-title");
  const loading = document.getElementById("image-preview-loading");
  const openLink = document.getElementById("image-preview-open");

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-image-preview]");
    if (!trigger) return;

    const src = trigger.dataset.imageSrc;
    const name = trigger.dataset.imageName || "Image preview";
    if (!src) return;

    image.hidden = true;
    loading.hidden = false;
    image.alt = name;
    title.textContent = name;
    openLink.href = src;
    image.src = src;
    modal.show();
  });

  image.addEventListener("load", () => {
    loading.hidden = true;
    image.hidden = false;
  });

  image.addEventListener("error", () => {
    loading.hidden = true;
    title.textContent = `Could not preview ${image.alt}`;
  });

  modalElement.addEventListener("hidden.bs.modal", () => {
    image.removeAttribute("src");
    image.hidden = true;
  });
})();
