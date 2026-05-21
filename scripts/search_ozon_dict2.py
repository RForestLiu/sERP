#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Search Ozon dictionary values with proper Russian encoding."""
import json, requests, os, sys
from dotenv import load_dotenv
load_dotenv()

CLIENT_ID = os.getenv('OZON_ANLING_CLIENT_ID')
API_KEY = os.getenv('OZON_ANLING_API_KEY')
BASE_URL = 'https://api-seller.ozon.ru'
HEADERS = {'Client-Id': CLIENT_ID, 'Api-Key': API_KEY, 'Content-Type': 'application/json'}

def search_values(attr_id, search_term, cat_id=17027904, type_id=93338):
    """Search for dictionary values by keyword."""
    payload = {
        'attribute_id': attr_id,
        'description_category_id': cat_id,
        'type_id': type_id,
        'search': search_term,
        'limit': 20,
        'last_value_id': 0,
    }
    # Print raw bytes to diagnose encoding
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    resp = requests.post(
        f'{BASE_URL}/v1/description-category/attribute/values/search',
        headers=HEADERS,
        data=body,
        verify=False
    )
    print(f'  Search attr={attr_id} "{search_term}": status={resp.status_code}')
    if resp.status_code != 200:
        print(f'    Error: {resp.text[:300]}')
        return []
    result = resp.json()
    vals = result.get('result', [])
    return vals

# Search for values we need
searches = [
    # Brand
    (85, 'Bostanten'),
    (85, 'Travelambo'),
    # Closure type - try Russian terms
    (5344, 'кнопка'),
    (5344, 'молния'),
    (5344, 'замок'),
    # Target audience
    (9390, 'женский'),
    (9390, 'мужской'),
    # Colors
    (10096, 'черный'),
    (10096, 'бежевый'),
    (10096, 'коричневый'),
    (10096, 'розовый'),
    (10096, 'красный'),
]

for attr_id, term in searches:
    vals = search_values(attr_id, term)
    for v in vals:
        vid = v.get('id')
        vval = v.get('value', '')
        # Also print hex of first few bytes to debug encoding
        raw = vval.encode('utf-8', errors='replace')
        print(f'    id={vid} value="{vval}" hex={raw[:30].hex()}')
    if not vals:
        print(f'    No results')
