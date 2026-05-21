"""
Search Ozon dictionary values for problematic WALLET-0002 attributes.
Saves results to data/ozon_dict_search_results.json
"""
import json, os, requests
from dotenv import load_dotenv
load_dotenv()

CLIENT_ID = os.getenv('OZON_ANLING_CLIENT_ID')
API_KEY = os.getenv('OZON_ANLING_API_KEY')
BASE_URL = 'https://api-seller.ozon.ru'
HEADERS = {'Client-Id': CLIENT_ID, 'Api-Key': API_KEY, 'Content-Type': 'application/json'}

def get_all_values(attr_id, cat_id=17027904, type_id=93338):
    """Fetch all dictionary values for an attribute."""
    values = []
    last_id = 0
    page = 0
    while True:
        page += 1
        resp = requests.post(
            f'{BASE_URL}/v1/description-category/attribute/values',
            headers=HEADERS,
            json={
                'attribute_id': attr_id,
                'description_category_id': cat_id,
                'type_id': type_id,
                'limit': 1000,
                'last_value_id': last_id,
            },
            verify=False
        )
        if resp.status_code != 200:
            print(f'  ERROR page {page}: {resp.text[:200]}')
            break
        result = resp.json()
        batch = result.get('result', [])
        if not batch:
            break
        values.extend(batch)
        last_id = batch[-1]['id']
        if len(batch) < 1000:
            break
    return values

# Attributes to search
attr_ids = {
    85: 'Brand (Бренд)',
    5344: 'Closure Type (Тип застежки)',
    9390: 'Target Audience (Целевая аудитория)',
    10096: 'Color (Цвет товара)',
}

results = {}

for attr_id, name in attr_ids.items():
    print(f'Fetching attr {attr_id}: {name}...')
    values = get_all_values(attr_id)
    print(f'  Got {len(values)} values')
    results[attr_id] = {
        'name': name,
        'total': len(values),
        'values': values,
    }

# Also fetch the brand list endpoint to check if it works
print('\nTrying /v1/brand/list...')
resp = requests.get(f'{BASE_URL}/v1/brand/list', headers=HEADERS, verify=False)
print(f'  Status: {resp.status_code}')
if resp.status_code == 200:
    results['brand_list'] = resp.json()

# Save all results
output_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'ozon_dict_search_results.json')
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f'\nResults saved to {output_path}')

# Now print a summary of the values we care about
print('\n=== KEY VALUES ===')
search_terms = {
    85: ['Travelambo', 'Bostanten', 'BOSTANTEN'],
    5344: ['кнопка', 'молния', 'замок', 'застежка', 'липучка'],
    9390: ['женский', 'женщины', 'для женщин', 'женская'],
    10096: ['черный', 'бежевый', 'коричневый', 'розовый', 'красный', 'черная'],
}

for attr_id, terms in search_terms.items():
    vals = results[attr_id]['values']
    found = []
    for v in vals:
        val = v.get('value', '')
        for term in terms:
            if term.lower() in val.lower():
                found.append(v)
                break
    if found:
        print(f'\nAttr {attr_id} matches:')
        for fv in found:
            print(f'  id={fv["id"]} value="{fv["value"]}"')
    else:
        print(f'\nAttr {attr_id}: NO matches for {terms}')
