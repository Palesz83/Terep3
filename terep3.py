"""Launcher kept at the project root for uv and PyInstaller."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from terep3.game import Game

_game = None


def update():
    if _game is not None:
        _game.update()


def input(key):
    if _game is not None:
        _game.handle_input(key)


def main():
    global _game
    _game = Game()
    _game.run()


if __name__ == "__main__":
    main()
