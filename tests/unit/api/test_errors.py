from http import HTTPStatus


def test_unknown_path_returns_error_document(client):
    """Framework 404s also follow the spec's error document shape."""
    response = client.get("/nope")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {"errors": [{"code": "not_found", "description": "Not Found"}]}


def test_wrong_method_returns_error_document(client):
    """Framework 405s also follow the spec's error document shape."""
    response = client.get("/charts")

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert response.json() == {"errors": [{"code": "method_not_allowed", "description": "Method Not Allowed"}]}
    # Starlette's 405 advertises the allowed methods; the remap must keep headers
    assert "POST" in response.headers.get("allow", "")
