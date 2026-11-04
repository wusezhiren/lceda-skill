#!/usr/bin/env python3
import argparse
import json
import math
import re
from pathlib import Path


def parse_source(source):
    stack = [[]]
    for token in re.findall(r'\(|\)|"(?:\\.|[^"\\])*"|[^\s()]+', source):
        if token == '(':
            stack.append([])
        elif token == ')':
            if len(stack) < 2:
                raise ValueError('Unbalanced DSN')
            stack[-2].append(stack.pop())
        else:
            stack[-1].append(token)
    if len(stack) != 1 or len(stack[0]) != 1:
        raise ValueError('Incomplete DSN')
    return stack[0][0]


def children(node, name):
    return [child for child in node if isinstance(child, list) and child and child[0] == name]


def serialize(node, depth=0):
    if not isinstance(node, list):
        return node
    if not any(isinstance(child, list) for child in node):
        return '(' + ' '.join(node) + ')'
    opening = []
    nested = []
    for child in node:
        if isinstance(child, list):
            nested.append('  ' * (depth + 1) + serialize(child, depth + 1))
        elif nested:
            raise ValueError('Unsupported DSN mixed scope')
        else:
            opening.append(child)
    return '(' + ' '.join(opening) + '\n' + '\n'.join(nested) + '\n' + '  ' * depth + ')'


def normalize(document, regions, clearance_mil=None):
    if not regions:
        raise ValueError('An explicit nonempty region manifest is required')
    resolution = children(document, 'resolution')
    if len(resolution) != 1 or resolution[0][1] != 'mil':
        raise ValueError('Only verified mil-based LCEDA exports are supported')
    structure = children(document, 'structure')[0]
    library = children(document, 'library')[0]
    images = children(library, 'image')
    padstacks = {entry[1]: entry for entry in children(library, 'padstack')}
    networks = children(document, 'network')[0]
    net_pins = {token for network in children(networks, 'net')
                for group in children(network, 'pins') for token in group[1:]}
    converted = []
    for region in regions:
        identifier = region['id']
        candidates = {identifier, identifier.replace('e', '', 1)}
        matches = [(image, pin) for image in images for pin in children(image, 'pin')
                   if pin[2] in candidates]
        if len(matches) != 1:
            raise ValueError(f'Region must match exactly one DSN synthetic pin: {identifier}')
        image, pin = matches[0]
        placements = [place for group in children(children(document, 'placement')[0], 'component')
                      if group[1] == image[1] for place in children(group, 'place')]
        if len(placements) != 1 or placements[0][1] != image[1] or placements[0][4] != 'front' or any(
                float(placements[0][index]) != 0 for index in (2, 3, 5)):
            raise ValueError('Only identity-placed synthetic images are supported')
        if len(pin) != 5:
            raise ValueError('Rotated or extended region pins require manual review')
        if f'{image[1]}-{pin[2]}' in net_pins:
            raise ValueError(f'Refusing to remove a connected pin: {identifier}')
        padstack = padstacks[pin[1]]
        shapes = children(padstack, 'shape')
        if len(shapes) != 1 or shapes[0][1][0] != 'polygon':
            raise ValueError(f'Region is not a single polygon: {identifier}')
        polygon = shapes[0][1]
        expected_layer = {1: 'TopLayer', 2: 'BottomLayer'}.get(region.get('layer'))
        if expected_layer is None or polygon[1] != expected_layer:
            raise ValueError(f'Region layer does not match manifest: {identifier}')
        if sum(candidate[1] == pin[1] for entry in images for candidate in children(entry, 'pin')) != 1:
            raise ValueError(f'Region padstack is shared: {identifier}')
        coordinates = polygon[3:]
        if len(coordinates) < 6 or len(coordinates) % 2:
            raise ValueError(f'Invalid region polygon: {identifier}')
        absolute = []
        for offset, coordinate in enumerate(coordinates):
            origin = float(pin[3 + offset % 2])
            value = float(coordinate) + origin
            if not math.isfinite(value):
                raise ValueError('Non-finite region coordinates')
            absolute.append(f'{value:.6f}'.rstrip('0').rstrip('.'))
        structure.append(['keepout', json.dumps('region_' + identifier),
                          ['polygon', polygon[1], '0', *absolute]])
        image.remove(pin)
        library.remove(padstack)
        converted.append({'id': identifier, 'dsn_pin': pin[2], 'layer': polygon[1]})
    if clearance_mil is not None:
        def update(node):
            if not isinstance(node, list):
                return
            if node and node[0] in ('clear', 'clearance') and len(node) > 1:
                try:
                    node[1] = str(max(float(node[1]), clearance_mil))
                except ValueError:
                    raise ValueError('Unexpected DSN clearance value')
            for child in node:
                update(child)
        update(document)
    return converted


def main():
    parser = argparse.ArgumentParser(description='Convert verified LCEDA region pseudo-pads to Specctra keepouts.')
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--clearance-mil', type=float)
    arguments = parser.parse_args()
    if arguments.input.resolve() == arguments.output.resolve():
        parser.error('Input and output must differ')
    if arguments.clearance_mil is not None and (not math.isfinite(arguments.clearance_mil) or arguments.clearance_mil <= 0):
        parser.error('Clearance must be positive')
    manifest = json.loads(arguments.manifest.read_text())
    document = parse_source(arguments.input.read_text())
    converted = normalize(document, manifest['regions'], arguments.clearance_mil)
    arguments.output.write_text(serialize(document) + '\n')
    print(json.dumps({'converted': converted, 'clearance_mil': arguments.clearance_mil,
                      'output': str(arguments.output)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
