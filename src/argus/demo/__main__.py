"""Allow the demo dry run to be invoked as a module."""

import argparse

from argus.demo.cli import configure_parser, run

parser = argparse.ArgumentParser(prog="python -m argus.demo", description="Print the demo playback timeline.")
configure_parser(parser)
raise SystemExit(run(parser.parse_args()))
