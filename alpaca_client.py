from alpaca.broker.client import BrokerClient
import os

# Replace with your API key and secret
API_KEY = os.getenv("ALPACA_API")
API_SECRET = os.getenv("ALPACA_SECRET")

# Initialize the broker client
broker_client = BrokerClient(api_key=API_KEY, secret_key=API_SECRET)

def create_account():
    # Account data
    account_data = {
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

    try:
        # Send POST request to create an account
        response = broker_client.post("/accounts", json=account_data)
        print(f"Account created: {response}")
        return response
    except Exception as e:
        print(f"Error creating account: {e}")
        return None

if __name__ == "__main__":
    create_account()
