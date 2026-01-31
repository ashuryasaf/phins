# PHINS Delivery Bidding System

## Overview

The AI-powered Delivery Bidding System enables location-based, bidding-oriented B2B delivery services integrated with the PHINS health wallet system.

## Architecture

### Flow

1. **Customer Purchase** → Customer buys product using health wallet
2. **Delivery Request** → Delivery preferences uploaded to bidding system
3. **Supplier Notification** → Eligible delivery suppliers notified (location-based)
4. **Bidding** → Suppliers place bids (price, estimated delivery time)
5. **AI Evaluation** → AI evaluates bids (price, supplier rating, delivery time, location)
6. **Acceptance** → Customer/system approves best bid
7. **Execution** → Delivery executed with real-time tracking
8. **Settlement** → Payment settled from health wallet to delivery supplier
9. **Feedback** → Supplier and customer ratings updated
10. **Pipeline Refresh** → Wallets and transactions refreshed

## Components

### 1. Delivery Bidding Service (`services/delivery_bidding_service.py`)

Core service managing the complete delivery bidding workflow.

#### Key Features

- **Create Delivery Requests**: Customer initiates delivery with pickup/delivery locations
- **Submit Bids**: Suppliers bid on delivery requests
- **AI Bid Evaluation**: Machine learning evaluates bids based on:
  - Price (40% weight)
  - Supplier rating (25% weight)
  - Delivery time (20% weight)
  - Reliability score (15% weight)
- **Real-time Tracking**: Status updates with GPS coordinates
- **Payment Integration**: Health wallet debit, supplier credit
- **Performance Metrics**: Track supplier performance over time

#### Usage Example

```python
from services.delivery_bidding_service import get_delivery_bidding_service

# Initialize service
delivery_service = get_delivery_bidding_service()

# Create delivery request
request = delivery_service.create_delivery_request(
    customer_id='CUST-001',
    order_id='ORD-001',
    pickup_location={
        'address': '123 Main St',
        'city': 'New York',
        'lat': 40.7128,
        'lon': -74.0060
    },
    delivery_location={
        'address': '456 Broadway',
        'city': 'New York',
        'lat': 40.7209,
        'lon': -74.0007
    },
    item_details={
        'description': 'Medical supplies',
        'weight_kg': 5.0,
        'fragile': True
    },
    urgency='standard',
    max_budget=50.00
)

# Supplier submits bid
bid = delivery_service.submit_bid(
    request_id=request['request_id'],
    supplier_id='SUP-001',
    bid_amount=35.00,
    estimated_pickup_time='2024-01-15T10:00:00Z',
    estimated_delivery_time='2024-01-15T12:00:00Z',
    vehicle_type='van'
)

# AI evaluates bids and recommends winner
evaluation = delivery_service.evaluate_bids_ai(
    request_id=request['request_id'],
    auto_accept=True
)

# Track delivery
status = delivery_service.get_delivery_status(
    delivery_id=evaluation['acceptance']['delivery_id']
)
```

### 2. API Endpoints (`web_portal/api_delivery_bidding.py`)

RESTful API for delivery bidding operations.

#### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/delivery/request` | Create delivery request |
| POST | `/api/delivery/bid` | Submit supplier bid |
| GET | `/api/delivery/bids/<request_id>` | Get bids for request |
| POST | `/api/delivery/accept-bid` | Accept winning bid |
| POST | `/api/delivery/evaluate-bids` | AI bid evaluation |
| POST | `/api/delivery/update-status` | Update delivery status |
| GET | `/api/delivery/track/<delivery_id>` | Track delivery |
| POST | `/api/delivery/pay` | Process payment |
| POST | `/api/delivery/rate` | Rate delivery |
| GET | `/api/delivery/supplier-performance/<supplier_id>` | Get supplier metrics |

#### API Request Examples

**Create Delivery Request:**
```bash
curl -X POST http://localhost:8000/api/delivery/request \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "CUST-001",
    "order_id": "ORD-001",
    "pickup_location": {
      "address": "123 Main St",
      "city": "New York",
      "lat": 40.7128,
      "lon": -74.0060
    },
    "delivery_location": {
      "address": "456 Broadway",
      "city": "New York",
      "lat": 40.7209,
      "lon": -74.0007
    },
    "item_details": {
      "description": "Medical supplies",
      "weight_kg": 5.0
    },
    "urgency": "standard",
    "max_budget": 50.00
  }'
```

**Submit Bid:**
```bash
curl -X POST http://localhost:8000/api/delivery/bid \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "DELREQ-20240115120000-ABC123",
    "supplier_id": "SUP-001",
    "bid_amount": 35.00,
    "estimated_pickup_time": "2024-01-15T10:00:00Z",
    "estimated_delivery_time": "2024-01-15T12:00:00Z",
    "vehicle_type": "van"
  }'
```

**Track Delivery:**
```bash
curl http://localhost:8000/api/delivery/track/DEL-20240115120000-XYZ789
```

### 3. Location-Based Matching

The system uses the **Haversine formula** to calculate distances between coordinates:

```python
def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculate great-circle distance in kilometers"""
    R = 6371  # Earth radius in km
    # ... Haversine calculation ...
    return distance_km
```

### 4. AI Bid Evaluation

The AI scoring algorithm evaluates bids using weighted criteria:

```python
Score = (Price × 0.40) + (Rating × 0.25) + (Speed × 0.20) + (Reliability × 0.15)
```

- **Price Score**: Lower price = higher score
- **Rating Score**: Supplier rating (0-5 scale)
- **Speed Score**: Faster delivery = higher score
- **Reliability Score**: Historical on-time delivery rate

### 5. Delivery Status Workflow

```
confirmed → en_route_to_pickup → picked_up → in_transit → 
arriving → delivered → completed
```

Each status update includes:
- Timestamp
- GPS coordinates (optional)
- Notes from driver
- Updated by (supplier ID)

## Integration with Health Wallet

### Payment Flow

1. **Delivery Accepted** → Amount held (not yet debited)
2. **Delivery Completed** → Customer payment processed
3. **Wallet Debited** → Amount deducted from health wallet
4. **Supplier Credited** → Supplier receives payment (settlement cycle)
5. **Transaction Recorded** → Ledger updated with delivery payment

### Health Wallet Transaction Example

```json
{
  "transaction_id": "TXN-DEL-20240115-001",
  "type": "delivery_payment",
  "amount": -35.00,
  "description": "Delivery payment for DEL-20240115120000-XYZ789",
  "delivery_id": "DEL-20240115120000-XYZ789",
  "supplier_id": "SUP-001",
  "previous_balance": 1000.00,
  "balance_after": 965.00,
  "timestamp": "2024-01-15T12:30:00Z"
}
```

## Data Integrity

The Platform Integrity Service validates:

- **Delivery Requests** → Valid customer, order references
- **Bids** → Valid supplier, within budget
- **Deliveries** → Request/bid/order consistency
- **Payments** → Wallet balance sufficient, transaction recorded

## Performance Metrics

### Supplier Metrics

Tracked for each delivery supplier:

- Total deliveries
- Total revenue
- Average rating (1-5 stars)
- Reliability score (0-1)
- On-time delivery percentage
- Customer satisfaction

### System Metrics

Tracked across the platform:

- Average bid count per request
- Average delivery time
- On-time delivery rate
- Average delivery cost
- Customer satisfaction rate

## Testing

Comprehensive test suite in `tests/test_delivery_bidding.py`:

- Request creation
- Bid submission
- Multi-supplier bidding
- Budget validation
- AI evaluation
- Bid acceptance
- Status tracking
- Payment processing
- Rating system
- Distance calculations

Run tests:
```bash
pytest tests/test_delivery_bidding.py -v
```

## Future Enhancements

1. **Route Optimization**: Integrate with mapping APIs for optimal routes
2. **Multi-Stop Deliveries**: Support for multiple pickup/delivery locations
3. **Delivery Pools**: Group multiple deliveries for efficiency
4. **Real-time Notifications**: Push notifications for status updates
5. **Predictive Analytics**: Predict delivery times based on historical data
6. **Dynamic Pricing**: Adjust pricing based on demand
7. **Blockchain Integration**: Immutable delivery records

## Security Considerations

- **Authentication**: All API endpoints require authentication
- **Authorization**: Suppliers can only bid on requests they're eligible for
- **Payment Security**: Wallet transactions use secure callbacks
- **Data Privacy**: Customer locations encrypted in transit
- **Audit Trail**: Complete audit log of all delivery operations
