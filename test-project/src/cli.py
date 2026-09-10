#!/usr/bin/env python3
"""Configuration service CLI."""

import sys
from pathlib import Path

from src.config_service import build_report, load_config


def main():
    if len(sys.argv) < 2:
        print("Usage: config-service <config-file>")
        sys.exit(1)
    
    config_path = sys.argv[1]
    
    try:
        config = load_config(config_path)
        report = build_report(config)
        print(report)
    except FileNotFoundError:
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
