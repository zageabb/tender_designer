from __future__ import annotations

from app import app
from services.sample_data import seed_sample_data


with app.app_context():
    result = seed_sample_data(app.config["DATA_DIR"])
    print(result)

