"""`.env` fills gaps; a real environment variable always wins.
python test_env_loader.py"""
import os, tempfile, pathlib
from app.config import _load_env

d = pathlib.Path(tempfile.mkdtemp())
env = d / ".env"
env.write_text(
    "# a comment\n"
    "\n"
    "FESTIVAL_API_KEY=fes_from_file\n"
    'QUOTED="quoted value"\n'
    "SINGLE='sq'\n"
    "export EXPORTED=works\n"          # README-style line pasted verbatim
    "SPACED  =  padded  \n"
    "junk-line-without-equals\n"
    "URL=https://x/y?a=1&b=2\n",       # '=' inside the value must survive
    encoding="utf-8")

os.environ.pop("FESTIVAL_API_KEY", None)
os.environ["ALREADY_SET"] = "from_real_env"
env.write_text(env.read_text(encoding="utf-8") + "ALREADY_SET=from_file\n",
               encoding="utf-8")

_load_env(env)

assert os.environ["FESTIVAL_API_KEY"] == "fes_from_file"
assert os.environ["QUOTED"] == "quoted value"
assert os.environ["SINGLE"] == "sq"
assert os.environ["EXPORTED"] == "works"
assert os.environ["SPACED"] == "padded"
assert os.environ["URL"] == "https://x/y?a=1&b=2"
assert os.environ["ALREADY_SET"] == "from_real_env"      # real env wins
assert "junk-line-without-equals" not in os.environ

_load_env(d / "nope.env")                                 # missing file is fine
print("env loader OK")
