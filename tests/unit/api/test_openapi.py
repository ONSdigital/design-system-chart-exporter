from app.main import app


def test_openapi_documents_the_error_contract():
    """The generated schema advertises every status the route can return, with the spec error document."""
    post = app.openapi()["paths"]["/charts"]["post"]

    # FastAPI auto-adds a 422; we strip it because validation is remapped to 400 (see errors.py + main.custom_openapi)
    assert set(post["responses"]) == {"201", "400", "413", "415", "500", "503"}
    assert "422" not in post["responses"]
    for status in ("400", "413", "415", "500", "503"):
        schema = post["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/ErrorDocument")


def test_openapi_documents_the_unhealthy_response():
    get = app.openapi()["paths"]["/health"]["get"]

    assert set(get["responses"]) == {"200", "429", "500"}
    assert get["responses"]["500"]["content"]["application/json"]["schema"]["$ref"].endswith("/HealthResponse")


def test_openapi_schema_is_cached():
    """A second call returns the same cached schema object (the fast path)."""
    first = app.openapi()
    second = app.openapi()

    assert first is second
