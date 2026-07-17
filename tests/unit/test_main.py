from http import HTTPStatus

def test_liveness(client):
    """Test the liveness endpoint."""
    response = client.get("/")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"message": "Chart generator is up and running"}
