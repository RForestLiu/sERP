from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STORE_ID = "ozon_anling"
OFFER_ID = "WALLET-0006-BLACK"
SKU = OFFER_ID


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def ozon_post(endpoint: str, payload: dict) -> dict:
    client_id = os.environ.get("OZON_ANLING_CLIENT_ID", "")
    api_key = os.environ.get("OZON_ANLING_API_KEY", "")
    if not client_id or not api_key:
        raise RuntimeError("OZON_ANLING_CLIENT_ID/OZON_ANLING_API_KEY is not configured")
    res = requests.post(
        f"https://api-seller.ozon.ru{endpoint}",
        headers={
            "Client-Id": client_id,
            "Api-Key": api_key,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )
    if res.status_code != 200:
        raise RuntimeError(f"{endpoint} HTTP {res.status_code}: {res.text[:1000]}")
    return res.json()


def upload_public_images() -> list[str]:
    configured = os.environ.get("OZON_WALLET0006_BLACK_IMAGE_URLS", "").strip()
    if configured:
        urls = [u.strip() for u in configured.replace("\n", ",").split(",") if u.strip()]
        if urls:
            return urls

    if "--upload-0x0" not in sys.argv:
        raise RuntimeError(
            "No public image URLs configured. Set OZON_WALLET0006_BLACK_IMAGE_URLS "
            "or rerun with --upload-0x0 after explicitly approving third-party public image hosting."
        )

    image_dir = DATA / "collect_amz_f5d272d6" / "images" / "Black"
    paths = sorted(image_dir.glob("*.png"))
    if len(paths) < 5:
        raise RuntimeError(f"Expected Black image set in {image_dir}, found {len(paths)}")

    urls: list[str] = []
    expires_hours = os.environ.get("OZON_IMAGE_EXPIRES_HOURS", "720")
    for path in paths[:6]:
        with path.open("rb") as fh:
            res = requests.post(
                "https://0x0.st",
                data={"expires": expires_hours},
                files={"file": (path.name, fh)},
                timeout=90,
            )
        if res.status_code != 200:
            raise RuntimeError(f"image upload failed for {path.name}: HTTP {res.status_code} {res.text[:300]}")
        url = res.text.strip()
        if not url.startswith("https://"):
            raise RuntimeError(f"image upload returned unexpected URL for {path.name}: {url}")
        urls.append(url)
        print(f"uploaded image {len(urls)}: {url}")
    return urls


def build_payload(image_urls: list[str]) -> dict:
    description = (
        "Женский кошелек Bostanten из прочного нейлона подходит для ежедневных дел, "
        "поездок и прогулок. Компактный формат удобно помещается в сумку, а съемный "
        "ремешок позволяет носить кошелек на запястье.\n\n"
        "Модель оснащена тремя отделениями на молнии, слотами для карт, карманом для "
        "монет и прозрачным окном для документа. RFID-защита помогает снизить риск "
        "считывания банковских карт.\n\n"
        "Размер изделия около 17.1 x 11.2 x 2.5 см, вес около 200 г. Черный цвет и "
        "шахматный узор легко сочетаются с повседневным стилем."
    )
    title = "Кошелек Bostanten WALLET-0006, черный"
    attrs = [
        {"id": 85, "values": [{"dictionary_value_id": 971068372, "value": "Bostanten"}]},
        {"id": 4180, "values": [{"value": title}]},
        {"id": 4191, "values": [{"value": description}]},
        {"id": 4383, "values": [{"value": "200"}]},
        {"id": 4384, "values": [{"value": "Кошелек, съемный ремешок"}]},
        {"id": 4389, "values": [{"dictionary_value_id": 90296, "value": "Китай"}]},
        {"id": 5299, "values": [{"value": "17.1"}]},
        {"id": 5309, "values": [{"dictionary_value_id": 61965, "value": "Нейлон"}]},
        {"id": 5311, "values": [{"dictionary_value_id": 61936, "value": "Металл"}]},
        {"id": 5313, "values": [{"dictionary_value_id": 62040, "value": "Полиэстер"}]},
        {"id": 5344, "values": [{"dictionary_value_id": 60850, "value": "Молния"}]},
        {"id": 5355, "values": [{"value": "11.2"}]},
        {"id": 6573, "values": [{"value": "2.5"}]},
        {"id": 8229, "values": [{"dictionary_value_id": 93338, "value": "Кошелек"}]},
        {"id": 9024, "values": [{"value": OFFER_ID}]},
        {"id": 9048, "values": [{"value": "WALLET-0006"}]},
        {"id": 9163, "values": [{"dictionary_value_id": 22881, "value": "Женский"}]},
        {"id": 9390, "values": [{"dictionary_value_id": 43241, "value": "Взрослая"}]},
        {"id": 9661, "values": [{"value": "1"}]},
        {"id": 9725, "values": [{"dictionary_value_id": 39116, "value": "Базовая коллекция"}]},
        {"id": 10096, "values": [{"dictionary_value_id": 61574, "value": "черный"}]},
        {"id": 10097, "values": [{"value": "черный"}]},
        {"id": 10400, "values": [{"dictionary_value_id": 970960203, "value": "Без гарантии"}]},
        {"id": 11650, "values": [{"value": "1"}]},
        {"id": 20926, "values": [
            {"dictionary_value_id": 971098553, "value": "3 отделения для купюр"},
            {"dictionary_value_id": 971109292, "value": "3 отделения для карт"},
            {"dictionary_value_id": 971136685, "value": "1 отделение для фото/удостоверения"},
        ]},
        {"id": 23171, "values": [{"value": "#женский_кошелек #кошелек_на_молнии #rfid_защита #кошелек_на_запястье"}]},
        {"id": 23249, "values": [{"value": "1"}]},
        {"id": 23287, "values": [{"dictionary_value_id": 972848865, "value": "Портмоне"}]},
    ]
    item = {
        "name": title,
        "offer_id": OFFER_ID,
        "barcode": "",
        "price": "99.00",
        "currency_code": "CNY",
        "vat": "0",
        "description_category_id": 17027904,
        "type_id": 93338,
        "description": description,
        "attributes": attrs,
        "images": image_urls,
        "weight": 200,
        "weight_unit": "g",
        "depth": 25,
        "width": 112,
        "height": 171,
        "dimension_unit": "mm",
    }
    return {"items": [item]}


def save_artifact(name: str, data: dict) -> Path:
    out_dir = DATA / "ozon_live"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    load_env()
    image_urls = upload_public_images()
    payload = build_payload(image_urls)
    save_artifact("wallet0006_black_payload.json", payload)

    report = {"offer_id": OFFER_ID, "image_urls": image_urls, "events": []}
    result = ozon_post("/v3/product/import", payload)
    task_id = result.get("result", {}).get("task_id")
    report["events"].append({"event": "import_submitted", "result": result})
    print(f"submitted task_id={task_id}")

    if task_id:
        for attempt in range(1, 21):
            time.sleep(6)
            info = ozon_post("/v1/product/import/info", {"task_id": task_id})
            report["events"].append({"event": "import_info", "attempt": attempt, "result": info})
            items = info.get("result", {}).get("items", [])
            print(f"poll {attempt}: items={len(items)}")
            if items:
                statuses = {item.get("offer_id"): item.get("status") for item in items}
                print(f"statuses={statuses}")
                if all(item.get("status") in {"imported", "failed"} for item in items):
                    break

    try:
        rating = ozon_post("/v1/product/rating-by-sku", {"skus": [SKU]})
        report["events"].append({"event": "content_rating", "result": rating})
        print(json.dumps(rating, ensure_ascii=False, indent=2))
    except Exception as exc:
        report["events"].append({"event": "content_rating_failed", "error": str(exc)})
        print(f"content rating unavailable yet: {exc}")

    path = save_artifact("wallet0006_black_live_report.json", report)
    print(f"saved report: {path}")


if __name__ == "__main__":
    main()
