#!/usr/bin/env python

import sys, getopt, datetime, uuid
import xml.etree.ElementTree as ET

# Change indentation of the outputed XML file.
def _pretty_print(current, parent=None, index=-1, depth=0):
  for i, node in enumerate(current):
    _pretty_print(node, current, i, depth + 1)
  if parent is not None:
    if index == 0:
      parent.text = '\n' + ('    ' * depth)
    else:
      parent[index - 1].tail = '\n' + ('    ' * depth)
    if index == len(parent) - 1:
      current.tail = '\n' + ('    ' * (depth - 1))

# Check if tag exists and is not-empty.
def _is_valid(root, path):
  return root.find(path) is not None and root.find(path).text is not None and root.find(path).text.strip() != ''

sample_mapping = {
  'depth': {'source': 'Depth', 'zero_ok': True, 'tostring': lambda s: s + ' m'},
  'temp': {'source': 'Temp', 'zero_ok': False, 'tostring': lambda s: s + ' C'},
  'pressure0': {'source': 'Press1', 'zero_ok': False, 'tostring': lambda s: s + ' bar'},
  'rbt': {'source': 'RBT', 'zero_ok': True, 'tostring': lambda s: s + ':00 min'},
  'heartbeat': {'source': 'Heartrate', 'zero_ok': False, 'tostring': lambda s: s},
}

# Parse the XML provided as input
stdin = sys.stdin.read()
root = ET.fromstring(stdin)

site_map = {}
new_root = ET.Element('divelog', {'program': 'subsurface', 'version': '3'})

# Process all the dives
divesites = ET.SubElement(new_root, 'divesites')
dives = ET.SubElement(new_root, 'dives')
for dive in root.findall('./Logbook/Dive'):
  siteid = False

  # Build the divesites group.
  if 'Name' in dive.find('Place').attrib:
    # TODO: Use more than place name
    name = dive.find('Place').attrib['Name']
    if name != '':
      # Check if site is already in site_map
      if name not in site_map and name != '':
        siteid = uuid.uuid4().hex[:8]
        site_map[name] = siteid
        ds = ET.SubElement(divesites, 'site', {
          'uuid': siteid,
          'name': dive.find('Country').attrib['Name'] + ', ' + dive.find('City').attrib['Name'] + ', ' + name,
        })
        if _is_valid(dive, './Place/Lat'):
          ds.attrib['gps'] = '{:.6f} {:.6f}'.format(float(dive.find('./Place/Lat').text), float(dive.find('./Place/Lon').text))
      else:
        siteid = site_map[name]

  # Build the dives group.
  dv = ET.SubElement(dives, 'dive', {
    'number': dive.find('Number').text,
  })
  if siteid:
    dv.attrib['divesiteid'] = siteid
  if _is_valid(dive, 'Divedate'):
    dv.attrib['date'] = dive.find('Divedate').text
  if _is_valid(dive, 'Entrytime'):
    dv.attrib['time'] = dive.find('Entrytime').text + ':00'
  if _is_valid(dive, 'Divetime'):
    dv.attrib['duration'] = '{:02.0f}:00 min'.format(float(dive.find('Divetime').text))

  if dive.find('Buddy') is not None and 'Names' in dive.find('Buddy').attrib and dive.find('Buddy').attrib['Names'] != '':
    ET.SubElement(dv, 'buddy').text = dive.find('Buddy').attrib['Names']
  # TODO Add notes

  dcyl = ET.SubElement(dv, 'cylinder')
  if _is_valid(dive, 'Tanksize'):
    tanksize = float(dive.find('Tanksize').text)
    dcyl.attrib['size'] = f'{tanksize:.1f} l'
    match tanksize:
      case 10.0:
        dcyl.attrib['description'] = '10L 232 bar'
      case 12.0:
        dcyl.attrib['description'] = '12L 232 bar'
      case 13.0:
        dcyl.attrib['description'] = '13L 232 bar'
      case 15.0:
        dcyl.attrib['description'] = '15L 232 bar'
      case 24.0:
        dcyl.attrib['description'] = 'D12 232 bar'

  if _is_valid(dive, 'PresS'):
    dcyl.attrib['start'] = '{:.1f} bar'.format(float(dive.find('PresS').text))
  if _is_valid(dive, 'PresE'):
    dcyl.attrib['end'] = '{:.1f} bar'.format(float(dive.find('PresE').text))

  # Add divecomputer group.
  dcpt = ET.SubElement(dv, 'divecomputer')
  if _is_valid(dive, 'Computer'):
    dcpt.attrib['model'] = dive.find('Computer').text

  # Add depth tag.
  depth = ET.SubElement(dcpt, 'depth', {
    'max': '{:.2f} m'.format(float(dive.find('Depth').text)),
  })
  if _is_valid(dive, 'DepthAvg'):
    depth.attrib['mean'] = '{:.2f} m'.format(float(dive.find('DepthAvg').text))

  # Add temperature tag.
  if _is_valid(dive, 'Airtemp') or _is_valid(dive, 'Watertemp'):
    temp = ET.SubElement(dcpt, 'temperature')
    if _is_valid(dive, 'Airtemp') and dive.find('Airtemp').text != '0.00':
      temp.attrib['air'] = dive.find('Airtemp').text + ' C'
    if _is_valid(dive, 'Watertemp'):
      temp.attrib['water'] = dive.find('Watertemp').text + ' C'

  # Add water tag.
  if _is_valid(dive, 'Water'):
    match dive.find('Water').text:
      case 'Salt':
        ET.SubElement(dcpt, 'water', {'salinity': '1025 g/l'})
      case 'Fresh':
        ET.SubElement(dcpt, 'water', {'salinity': '1000 g/l'})

  ev = ET.SubElement(dcpt, 'event', {'time': '0:00 min', 'type': '25', 'flags': '1', 'name': 'gaschange', 'cylinder': '0'})

  # Process O2 mix.
  if _is_valid(dive, 'O2'):
    o2 = float(dive.find('O2').text)
    if o2 != 21.0:
      dcyl.attrib['o2'] = f'{o2:.1f}%'
      ev.attrib['o2'] = f'{o2:.1f}%'

  # Each samples/waypoint group will become a sample element.
  last_sample = None
  time_offset = int(dive.find('ProfileInt').text) if _is_valid(dive, 'ProfileInt') else 0
  for sample in dive.findall('./Profile/P'):
    s = ET.SubElement(dcpt, 'sample')
    s.attrib['time'] = '{:02d}:{:02d} min'.format(*divmod(int(sample.attrib['Time']) - time_offset, 60))
    for name, info in sample_mapping.items():
      if (val := sample.find(info['source'])) is not None:
        if (info['zero_ok'] or float(val.text) != 0.0) and (name in ('time', 'depth') or last_sample is None or val.text != last_sample.find(info['source']).text):
          s.attrib[name] = info['tostring'](val.text)
    # Store sample to compare with the next one.
    last_sample = sample

# Correct the indentation
_pretty_print(new_root);

# And now prepare the output string
output = ET.tostring(root, encoding='unicode', xml_declaration=False, short_empty_elements=False)

print(ET.tostring(new_root, encoding='unicode', xml_declaration=False))
