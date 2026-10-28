import logging
import requests
from django.conf import settings

logger = logging.getLogger('nova_poshta')

class NovaPoshtaAPI:
    BASE_URL = "https://api.novaposhta.ua/v2.0/json/"
    API_KEY = settings.NOVA_POSHTA_API_KEY

    @classmethod
    def _post(cls, payload):
        called_method = payload.get("calledMethod")
        last_error = None
        for _ in range(2):
            try:
                response = requests.post(cls.BASE_URL, json=payload, timeout=20)
                response.encoding = 'utf-8'
                return response.json()
            except requests.exceptions.RequestException as e:
                last_error = e
                logger.error("Nova Poshta %s request failed: %s", called_method, e)
            except ValueError as e:
                last_error = e
                logger.error("Nova Poshta %s returned invalid JSON: %s", called_method, e)
        raise last_error

    @classmethod
    def get_regions(cls):
        payload = {
            "apiKey": cls.API_KEY,
            "modelName": "Address",
            "calledMethod": "getAreas",
            "methodProperties": {}
        }
        return cls._post(payload)

    @classmethod
    def get_cities(cls, region_ref):
        cities = []
        page = 1
        while page <= 20:
            payload = {
                "apiKey": cls.API_KEY,
                "modelName": "Address",
                "calledMethod": "getCities",
                "methodProperties": {
                    "AreaRef": region_ref,
                    "Limit": "500",
                    "Page": str(page),
                }
            }
            response_data = cls._post(payload)
            chunk = response_data.get("data") or []
            cities.extend(chunk)
            total = int((response_data.get("info") or {}).get("totalCount") or 0)
            logger.debug("get_cities page %s: %s of %s", page, len(cities), total)
            if not chunk or len(cities) >= total:
                break
            page += 1
        return {"success": True, "data": cities}

    @classmethod
    def get_branches(cls, city_ref):
        payload = {
            "apiKey": cls.API_KEY,
            "modelName": "Address",
            "calledMethod": "getWarehouses",
            "methodProperties": {
                "CityRef": city_ref
            }
        }
        response_data = cls._post(payload)
        logger.debug("get_branches count: %s", len(response_data.get("data") or []))
        return response_data

    @classmethod
    def get_postomats(cls, city_ref):
        payload = {
            "apiKey": cls.API_KEY,
            "modelName": "AddressGeneral",
            "calledMethod": "getPostomats",
            "methodProperties": {
                "CityRef": city_ref
            }
        }
        response_data = cls._post(payload)
        logger.debug("get_postomats count: %s", len(response_data.get("data") or []))
        return response_data
