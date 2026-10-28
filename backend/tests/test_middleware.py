from app.middleware import RequestBodyLimit


async def test_chunked_body_limit_applies_before_parser():
    called = False
    async def app(scope, receive, send):
        nonlocal called
        called = True
    chunks = iter([{"type": "http.request", "body": b"1234", "more_body": True}, {"type": "http.request", "body": b"5678", "more_body": False}])
    async def receive():
        return next(chunks)
    messages = []
    async def send(message):
        messages.append(message)
    await RequestBodyLimit(app, max_bytes=6)({"type": "http", "method": "POST", "headers": []}, receive, send)
    assert not called
    assert messages[0]["status"] == 413


async def test_accepted_chunked_upload_reaches_parser_unchanged():
    received = []
    async def app(scope, receive, send):
        received.append(await receive())
    chunks = iter([{"type": "http.request", "body": b"1234", "more_body": True}, {"type": "http.request", "body": b"56", "more_body": False}])
    async def receive():
        return next(chunks)
    async def send(message):
        pass
    await RequestBodyLimit(app, max_bytes=6)({"type": "http", "method": "POST"}, receive, send)
    assert received[0]["body"] == b"123456" and not received[0]["more_body"]
