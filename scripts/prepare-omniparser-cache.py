#!/usr/bin/env python3
"""Prepare the pinned OmniParser V2 cache outside the production runtime."""

from __future__ import annotations

from haykal.perception.cache_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
