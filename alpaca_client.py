from alpaca.broker.client import BrokerClient
import os

# Replace with your API key and secret
API_KEY = os.getenv("ALPACA_API")
API_SECRET = os.getenv("ALPACA_SECRET")

if not API_KEY or not API_SECRET:
    raise ValueError("Alpaca API keys are missing. Please set ALPACA_API and ALPACA_SECRET environment variables.")

# Initialize the broker client
broker_client = BrokerClient(api_key=API_KEY, secret_key=API_SECRET)

def create_account(data):
    """
    Create an Alpaca account using the Broker API.
    
    Args:
        data (dict): A dictionary containing contact and identity information.
    
    Returns:
        dict: The response from the Alpaca API.
    """
    try:
        # Pass the payload directly without using `json=`
        response = broker_client.post("/accounts", data=data)
        print(f"Account created successfully: {response}")
        return response
    except Exception as e:
        print(f"Error creating account: {e}")
        return {"error": str(e)}

if __name__ == "__main__":
    # Test data for creating an account
    test_data = {
        "contact": {
            "email_address": "example@example.com",
            "phone_number": "1234567890",
            "city": "New York",
            "state": "NY",
            "postal_code": "10001",
            "country": "US",
        },
        "identity": {
            "given_name": "John",
            "family_name": "Doe",
            "dob": "1990-01-01",
            "tax_id": "123456789",
            "tax_id_type": "SSN",
        },
    }

    create_account(test_data)
