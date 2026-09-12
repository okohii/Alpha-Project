from app.cli.launcher import _parser


def test_default_mode_is_avatar() -> None:
    args = _parser().parse_args([])
    assert args.mode is None


def test_chat_is_the_only_text_ui_mode() -> None:
    args = _parser().parse_args(["chat"])
    assert args.mode == "chat"


def test_macros_remains_a_separate_ui() -> None:
    args = _parser().parse_args(["macros"])
    assert args.mode == "macros"
