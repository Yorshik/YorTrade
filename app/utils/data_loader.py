import json
from pathlib import Path

from app.data.models import PhraseType

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


async def load_server_data(app) -> dict[str, int]:
    companies = json.loads((DATA_DIR / "companies_ru.json").read_text(encoding="utf-8"))

    stats = {
        "assets_created": 0,
        "phrases_created": 0,
    }

    for company_payload in companies:
        asset, asset_created = await app.data.asset.get_or_create(
            name=company_payload["name"],
        )
        stats["assets_created"] += int(asset_created)

        for phrase_type, payload_key in (
            (PhraseType.GROWTH, "growth_phrases"),
            (PhraseType.STABLE, "stable_phrases"),
            (PhraseType.FALL, "fall_phrases"),
        ):
            for phrase in company_payload.get(payload_key, []):
                _, phrase_created = await app.data.phrase.get_or_create(
                    phrase_type=phrase_type,
                    phrase=phrase,
                    asset_id=asset.id,
                )
                stats["phrases_created"] += int(phrase_created)

    return stats
