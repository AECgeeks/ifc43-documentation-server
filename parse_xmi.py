import os
import sys
import json

sys.path.append(os.path.join(os.path.dirname(__file__), 'data', 'scripts'))
print(sys.path)

from xmi_document import xmi_document

fn = os.path.join(os.path.dirname(__file__), 'data', 'schemas', 'IFC.xml')
xmi_doc = xmi_document(fn)

entity_to_package = {}

for item in xmi_doc:
    if item.type == "ENTITY":
        entity_to_package[item.name] = item.package
        
json.dump(entity_to_package, open("entity_to_package.json", "w", encoding="utf-8"))
