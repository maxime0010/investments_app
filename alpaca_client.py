import os
import json
import base64
import requests
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize API keys
API_KEY = os.getenv("ALPACA_API")
API_SECRET = os.getenv("ALPACA_SECRET")

if not API_KEY or not API_SECRET:
    raise ValueError("API keys are missing. Please set ALPACA_API and ALPACA_SECRET environment variables.")

# Define base URL for Alpaca Broker API
BASE_URL = "https://broker-api.sandbox.alpaca.markets"
ENDPOINT = "/v1/accounts"

def _get_headers():
    """Generate headers for Alpaca API requests."""
    auth_header = base64.b64encode(f"{API_KEY}:{API_SECRET}".encode()).decode()
    return {
        "Authorization": f"Basic {auth_header}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
def create_account(data):
    """
    Create an Alpaca account using the Broker API.
    
    Args:
        data (dict): A dictionary containing contact and identity information.
    
    Returns:
        dict: The response from the Alpaca API or error details.
    """
    try:
        url = f"{BASE_URL}{ENDPOINT}"
        auth_header = base64.b64encode(f"{API_KEY}:{API_SECRET}".encode()).decode()

        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/json",
        }

        logger.info(f"Payload: {json.dumps(data, indent=2)}")
        response = requests.post(url, headers=headers, json=data)

        if response.status_code == 200:
            logger.info(f"Account created successfully: {response.json()}")
            return response.json()
        else:
            logger.error(f"Failed to create account: {response.status_code} - {response.text}")
            return {"error": response.text}

    except Exception as e:
        logger.error(f"Error creating account: {e}")
        return {"error": str(e)}

def fetch_account_details(account_id):
    """Fetch details of an Alpaca account."""
    try:
        url = f"{BASE_URL}/v1/accounts/{account_id}"
        headers = _get_headers()
        logger.info(f"Fetching account details for account_id: {account_id}")

        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        if response.status_code == 404:
            logger.warning(f"Account not found: {account_id}")
            return {"error": "Account not found."}
        elif response.status_code == 401:
            logger.error(f"Unauthorized access. Check your API credentials.")
            return {"error": "Unauthorized access to Alpaca API."}
        logger.error(f"HTTP error: {e}")
        return {"error": f"HTTP error: {e}"}
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching account details: {e}")
        return {"error": str(e)}

def fund_account(account_id, amount, funding_source="sandbox", direction="INCOMING"):
    """Fund an Alpaca account."""
    try:
        url = f"{BASE_URL}/v1/accounts/{account_id}/transfers"
        headers = _get_headers()
        payload = {
            "amount": float(amount),
            "funding_source": funding_source,
            "direction": direction
        }
        logger.info(f"Funding account {account_id} with payload: {payload}")

        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info(f"Funding successful: {response.json()}")
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error funding account: {e}")
        return {"error": str(e)}


if __name__ == "__main__":
    test_data = {
        "contact": {
            "email_address": "test1@gmail.com",
            "phone_number": "7065912538",
            "street_address": ["123 Main St"],  # Must be an array
            "city": "San Mateo",
            "state": "CA",
            "postal_code": "33345",
            "country": "US"
        },
        "identity": {
            "given_name": "John",
            "family_name": "Doe",
            "date_of_birth": "1990-01-01",
            "tax_id_type": "USA_SSN",
            "tax_id": "661-010-666",
            "country_of_citizenship": "USA",
            "country_of_birth": "USA",
            "country_of_tax_residence": "USA",
            "funding_source": ["employment_income", "savings"],  # Valid funding sources
            "annual_income_min": "10000",
            "annual_income_max": "10000",
            "total_net_worth_min": "10000",
            "total_net_worth_max": "10000",
            "liquid_net_worth_min": "10000",
            "liquid_net_worth_max": "10000",
            "liquidity_needs": "does_not_matter",
            "investment_experience_with_stocks": "over_5_years",
            "investment_experience_with_options": "over_5_years",
            "risk_tolerance": "conservative",
            "investment_objective": "market_speculation",
            "investment_time_horizon": "more_than_10_years",
            "marital_status": "MARRIED",
            "number_of_dependents": 5
        },
        "disclosures": {
            "is_control_person": False,
            "is_affiliated_exchange_or_finra": False,
            "is_affiliated_exchange_or_iiroc": False,
            "is_politically_exposed": False,
            "immediate_family_exposed": False
        },
        "agreements": [
            {
                "agreement": "customer_agreement",
                "signed_at": "2024-12-08T10:12:00Z",
                "ip_address": "127.0.0.1"
            },
            {
                "agreement": "options_agreement",
                "signed_at": "2024-12-08T10:12:00Z",
                "ip_address": "127.0.0.1"
            },
            {
                "agreement": "margin_agreement",
                "signed_at": "2024-12-08T10:12:00Z",
                "ip_address": "127.0.0.1"
            }
        ],
        "documents": [
            {
                "document_type": "identity_verification",
                "document_sub_type": "passport",
                "content": "/9j/Cg==",  # Base64-encoded content
                "mime_type": "image/jpeg"
            }
        ],
        "trusted_contact": {
            "given_name": "Jane",
            "family_name": "Smith",
            "email_address": "trusted.contact@example.com"
        },
        "additional_information": "",
        "account_type": "individual"
    }

    # Test account creation
    response = create_account(test_data)
    print(f"Response: {response}")
