from app.main import app


def test_openapi_documents_the_error_contract():
    """The generated schema advertises every status the route can return, with the spec error document."""
    post = app.openapi()["paths"]["/charts"]["post"]

    # 422 is FastAPI's auto-added validation response; we remap it to 400 (see errors.py)
    assert set(post["responses"]) == {"201", "400", "413", "415", "422", "500", "503"}
    for status in ("400", "413", "415", "500", "503"):
        schema = post["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/ErrorDocument")


def test_openapi_documents_the_unhealthy_response():
    get = app.openapi()["paths"]["/health"]["get"]

    assert set(get["responses"]) == {"200", "500"}
    assert get["responses"]["500"]["content"]["application/json"]["schema"]["$ref"].endswith("/HealthResponse")
