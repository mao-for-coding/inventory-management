"""
Tests for the POST /api/orders restocking order endpoint.
"""
import re
from datetime import date

import pytest

import mock_data


@pytest.fixture
def restore_orders():
    """Truncate orders appended during a test.

    POST /api/orders mutates the shared module-level list, so without this
    the created orders would leak into other tests in the same session.
    """
    original_count = len(mock_data.orders)
    yield
    del mock_data.orders[original_count:]


def _inventory_by_sku(client):
    """Build a sku -> inventory item lookup from the API."""
    response = client.get("/api/inventory")
    assert response.status_code == 200
    return {item["sku"]: item for item in response.json()}


class TestCreateOrder:
    """Test suite for POST /api/orders."""

    def test_create_order_success(self, client, restore_orders):
        """Test creating a valid restocking order."""
        response = client.post(
            "/api/orders",
            json={"items": [{"sku": "PCB-001", "quantity": 5}, {"sku": "TMP-201", "quantity": 2}]}
        )
        assert response.status_code == 201

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["customer"] == "Internal Restock"
        assert order["actual_delivery"] is None
        assert re.fullmatch(r"ORD-\d{4}-\d{4}", order["order_number"])
        assert len(order["items"]) == 2

    def test_create_order_prices_from_inventory(self, client, restore_orders):
        """Test that unit prices and total come from inventory, not the client."""
        inventory = _inventory_by_sku(client)
        response = client.post(
            "/api/orders",
            json={"items": [{"sku": "PCB-001", "quantity": 5}, {"sku": "TMP-201", "quantity": 2}]}
        )
        order = response.json()

        expected_total = 0
        for item in order["items"]:
            assert item["unit_price"] == inventory[item["sku"]]["unit_cost"]
            expected_total += item["quantity"] * item["unit_price"]
        assert abs(order["total_value"] - expected_total) < 0.01

    def test_create_order_lead_time(self, client, restore_orders):
        """Test that expected_delivery reflects the max lead time of the items."""
        inventory = _inventory_by_sku(client)
        skus = ["PCB-001", "TMP-201"]
        response = client.post(
            "/api/orders",
            json={"items": [{"sku": sku, "quantity": 1} for sku in skus]}
        )
        order = response.json()

        max_lead = max(inventory[sku]["lead_time_days"] for sku in skus)
        order_date = date.fromisoformat(order["order_date"])
        expected_delivery = date.fromisoformat(order["expected_delivery"])
        assert (expected_delivery - order_date).days == max_lead

    def test_create_order_ids_increment(self, client, restore_orders):
        """Test that consecutive orders get distinct incrementing ids."""
        first = client.post("/api/orders", json={"items": [{"sku": "PCB-001", "quantity": 1}]}).json()
        second = client.post("/api/orders", json={"items": [{"sku": "PCB-001", "quantity": 1}]}).json()
        assert int(second["id"]) == int(first["id"]) + 1
        assert first["order_number"] != second["order_number"]

    def test_create_order_unknown_sku(self, client, restore_orders):
        """Test that an unknown SKU returns 400."""
        response = client.post(
            "/api/orders",
            json={"items": [{"sku": "NOPE-999", "quantity": 1}]}
        )
        assert response.status_code == 400
        assert "NOPE-999" in response.json()["detail"]

    def test_create_order_empty_items(self, client):
        """Test that an empty items list fails validation."""
        response = client.post("/api/orders", json={"items": []})
        assert response.status_code == 422

    def test_create_order_invalid_quantity(self, client):
        """Test that zero or negative quantities fail validation."""
        for quantity in (0, -3):
            response = client.post(
                "/api/orders",
                json={"items": [{"sku": "PCB-001", "quantity": quantity}]}
            )
            assert response.status_code == 422


class TestSubmittedOrdersFlow:
    """Test suite for submitted orders flowing through GET /api/orders."""

    def test_submitted_order_in_status_filter(self, client, restore_orders):
        """Test that a created order appears under the Submitted status filter."""
        created = client.post("/api/orders", json={"items": [{"sku": "PCB-001", "quantity": 3}]}).json()

        response = client.get("/api/orders?status=Submitted")
        assert response.status_code == 200
        assert created["id"] in [order["id"] for order in response.json()]

    def test_submitted_order_in_unfiltered_list(self, client, restore_orders):
        """Test that a created order appears in the unfiltered order list."""
        created = client.post("/api/orders", json={"items": [{"sku": "PCB-001", "quantity": 3}]}).json()

        response = client.get("/api/orders")
        assert created["id"] in [order["id"] for order in response.json()]

    def test_submitted_order_by_id(self, client, restore_orders):
        """Test that a created order is retrievable by id."""
        created = client.post("/api/orders", json={"items": [{"sku": "PCB-001", "quantity": 3}]}).json()

        response = client.get(f"/api/orders/{created['id']}")
        assert response.status_code == 200
        assert response.json()["order_number"] == created["order_number"]

    def test_submitted_order_excluded_by_past_month_filter(self, client, restore_orders):
        """Test that month filters for past months exclude newly created orders.

        Created orders are dated today, so 2025 month filters must not include
        them — this documents the behavior the frontend relies on.
        """
        created = client.post("/api/orders", json={"items": [{"sku": "PCB-001", "quantity": 3}]}).json()

        response = client.get("/api/orders?month=2025-09")
        assert created["id"] not in [order["id"] for order in response.json()]
