#!/usr/bin/env python3
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


def verify(expected, exported):
    actual = defaultdict(set)
    for component in exported['components'].values():
        reference = component['props']['Designator']
        for number, pin in component.get('pinInfoMap', {}).items():
            if pin.get('net'):
                actual[pin['net']].add((reference, str(number)))
    remaining = dict(actual)
    differences = []
    aliases = {}
    for name, nodes in expected.items():
        wanted = {(reference, str(number)) for reference, number in nodes}
        found = remaining.get(name)
        if found == wanted:
            del remaining[name]
            continue
        candidates = [candidate for candidate, pins in remaining.items() if pins == wanted]
        if len(candidates) == 1 and re.match(r'^(N_|N\$|Net-)', name) and re.match(r'^(N_|N\$|Net-)', candidates[0]):
            aliases[name] = candidates[0]
            del remaining[candidates[0]]
            continue
        differences.append({'net': name, 'missing': sorted(wanted - (found or set())),
                            'extra': sorted((found or set()) - wanted)})
    return {'passed': not differences and not remaining, 'expected_nets': len(expected),
            'actual_nets': len(actual), 'expected_nodes': sum(len(nodes) for nodes in expected.values()),
            'actual_nodes': sum(len(nodes) for nodes in actual.values()), 'aliases': aliases,
            'differences': differences, 'unexpected_nets': sorted(remaining)}


def main():
    parser = argparse.ArgumentParser(description='Compare native EasyEDA component-pin networks with an expected nets mapping.')
    parser.add_argument('expected', type=Path)
    parser.add_argument('exported', type=Path)
    arguments = parser.parse_args()
    expected = json.loads(arguments.expected.read_text())
    report = verify(expected['nets'], json.loads(arguments.exported.read_text()))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
