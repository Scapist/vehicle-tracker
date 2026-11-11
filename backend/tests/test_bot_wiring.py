from app.bot.runner import build_application


def test_application_builds_offline_with_all_handlers():
    app = build_application("123456:TEST-TOKEN", [111])
    handlers = [h for group in app.handlers.values() for h in group]
    names = {type(h).__name__ for h in handlers}
    assert {"CommandHandler", "MessageHandler", "CallbackQueryHandler"} <= names
    assert len(handlers) == 6
