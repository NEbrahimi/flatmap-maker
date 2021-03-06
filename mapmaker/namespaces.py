#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019  David Brooks
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
#===============================================================================

import os

#===============================================================================

from rdflib import Graph
from rdflib.namespace import Namespace, NamespaceManager

import yaml

#===============================================================================

with open(os.path.join(os.path.split(__file__)[0], 'curie_map.yaml')) as f:
    curie_map = yaml.load(f, Loader=yaml.Loader)

SCICRUNCH_NS = NamespaceManager(Graph())
_namespaces = {}

for prefix, url in curie_map.items():
    ns = Namespace(url)
    SCICRUNCH_NS.bind(prefix, ns, override=True)
    _namespaces[prefix] = ns

#===============================================================================

def namespaces_dict():
    return _namespaces

#===============================================================================
