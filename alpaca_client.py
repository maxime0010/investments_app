import json
from datetime import datetime
from alpaca.broker.client import BrokerClient

# Initialize the broker client
API_KEY = os.getenv("ALPACA_API")
API_SECRET = os.getenv("ALPACA_SECRET")

if not API_KEY or not API_SECRET:
    raise ValueError("API keys are missing. Please set ALPACA_API and ALPACA_SECRET environment variables.")

broker_client = BrokerClient(api_key=API_KEY, secret_key=API_SECRET)

def create_account(data):
    """
    Create an Alpaca account using the Broker API.
    
    Args:
        data (dict): A dictionary containing contact, identity, and other required information.
    
    Returns:
        dict: The response from the Alpaca API or error details.
    """
    try:
        # Ensure the payload matches Alpaca API requirements
        logger.info(f"Sending payload: {json.dumps(data, indent=2)}")

        # Use the json= argument to send structured data
        response = broker_client.post("/v1/accounts", json=data)

        logger.info(f"Account created successfully: {response}")
        return response
    except Exception as e:
        logger.error(f"Error creating account: {str(e)}")
        return {"error": str(e)}

if __name__ == "__main__":
    # Test data
    test_data = {
        "contact": {
            "email_address": "test1@gmail.com",
            "phone_number": "7065912538",
            "street_address": ["123 Main St"],  # Must be an array of strings
            "city": "New York",
            "state": "NY",
            "postal_code": "10001",
            "country": "US"
        },
        "identity": {
            "given_name": "John",
            "family_name": "Doe",
            "date_of_birth": "1990-01-01",
            "tax_id_type": "USA_SSN",
            "tax_id": "123-45-6789",
            "country_of_citizenship": "USA",
            "country_of_birth": "USA",
            "country_of_tax_residence": "USA",
            "funding_source": ["employment_income"],  # Example funding source
            "annual_income_min": "10000",
            "annual_income_max": "50000",
            "total_net_worth_min": "50000",
            "total_net_worth_max": "100000",
            "liquid_net_worth_min": "10000",
            "liquid_net_worth_max": "50000",
            "liquidity_needs": "does_not_matter",
            "investment_experience_with_stocks": "over_5_years",
            "investment_experience_with_options": "over_5_years",
            "risk_tolerance": "moderate",
            "investment_objective": "growth",
            "investment_time_horizon": "3_to_5_years",
            "marital_status": "SINGLE",
            "number_of_dependents": 0
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
                "signed_at": datetime.utcnow().isoformat() + "Z",
                "ip_address": "127.0.0.1"
            },
            {
                "agreement": "margin_agreement",
                "signed_at": datetime.utcnow().isoformat() + "Z",
                "ip_address": "127.0.0.1"
            }
        ],
        "documents": [
            {
                "document_type": "identity_verification",
                "document_sub_type": "passport",
                "content": "/9j/Cg==",  # Base64 encoded document content
                "mime_type": "image/jpeg"
            }
        ],
        "trusted_contact": {
            "given_name": "Jane",
            "family_name": "Smith",
            "email_address": "trusted.contact@example.com"
        },
        "additional_information": "No additional info",
        "account_type": "individual"
    }

    # Create account
    response = create_account(test_data)
    print(f"Response: {response}")
