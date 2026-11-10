#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Камдык көчүрмөнү бош базага кайтаруу: python restore.py taxi-tap-20261110-0300.json.gz"""
import sys

import ops

if len(sys.argv) != 2:
    raise SystemExit("Колдонуу: python restore.py <файл.json.gz>")
ops.restore(sys.argv[1])
print("Бүттү.")
