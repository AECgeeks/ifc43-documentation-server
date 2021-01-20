import re
import os
import glob
import json
import hashlib
import subprocess

import ifcopenshell
import pydot
import pysolr
import markdown
from bs4 import BeautifulSoup

from flask import Flask, send_file, render_template, abort, url_for, request, send_from_directory

app = Flask(__name__)

base = '/IFC/RELEASE/IFC4x3/HTML'

def make_url(fragment): return base + '/' + fragment

entity_to_package = json.load(open("entity_to_package.json", encoding="utf-8"))

navigation_entries = [
    ("Cover", "Contents", "Foreword", "Introduction"),
    ("Scope", "Normative references", "Terms, definitions, and abbreviated terms", "Fundamental concepts and assumptions"),
    ("Core data schemas", "Shared element data schemas", "Domain specific data schemas", "Resource definition data schemas"),
    ("Computer interpretable listings", "Alphabetical listings", "Inheritance listings", "Diagrams"),
    ("Examples", "Change logs", "Bibliography", "Index")
]

def to_dict(x):
    if isinstance(x, (list, tuple)):
        return type(x)(map(to_dict, x))
    else:
        return {"title": x}

def make_entries(x):
    md_root = "data/docs/schemas"
    categories = [d for d in os.listdir(md_root) if os.path.isdir(os.path.join(md_root, d))]
        
    if isinstance(x, (list, tuple)):
        return type(x)(map(make_entries, x))
    
    elif x['title'] == 'Alphabetical listings':
        url = make_url('listing')
    elif type(x['number']) == int and x['number'] >= 5:
        url = make_url('chapter-%d/' % x['number'])
    else:
        url = '#'
    
    return dict(**x, url=url)

def make_counter(start=0):
    n = start
    def counter():
        nonlocal n
        n += 1
        if n > 14:
            return None
        if n > 8:
            return chr(ord('A') + n - 9)
        elif n >= 1:
            return n
    return counter
    
section_counter = make_counter(-4)
        
def number_entries(x):
    if isinstance(x, (list, tuple)) and set(map(type, x)) == {dict}:
        return type(x)(dict(**di, number=section_counter()) for i, di in enumerate(x))
    else:
        return type(x)(map(number_entries, x))
        
navigation_entries = make_entries(number_entries(to_dict(navigation_entries)))

def chapter_lookup(number=None, cat=None):

    def do_chapter_lookup(x):
        if isinstance(x, (list, tuple)):
            return next((v for v in map(do_chapter_lookup, x) if v is not None), None)
        if number is not None and x['number'] == number:
            return x
        if cat is not None and x['title'].split(" ")[0].lower() == cat:
            return x
            
    return do_chapter_lookup(navigation_entries)

entity_names = sorted(s.split('/')[-1][:-3] for s in glob.glob("data/docs/**/*.md", recursive=True))

S = ifcopenshell.ifcopenshell_wrapper.schema_by_name('IFC4X3_RC1')

def generate_inheritance_graph(current_entity):
    i = S.declaration_by_name(current_entity)
    g = pydot.Graph('dot_inheritance', graph_type='graph')
    di = {
        'rankdir': 'BT',
        'ranksep': 0.2
    }
    for kv in di.items():
        g.set(*kv)

    previous = None
    while i:
        n = pydot.Node(i.name())
        di = {
            'color':'black',
            'fillcolor':'grey43',
            'fontcolor':'white',
            'height':'0.3',
            'shape':'rectangle',
            'style':'filled',
            'width':'4'
        }
        for kv in di.items():
            n.set(*kv)
        g.add_node(n)
    
        if previous:
            g.add_edge(pydot.Edge(previous, n))
            
        previous = n
        
        i = i.supertype()
        
    return g.to_string()
    

def get_node_colour(n):
    try:
        i = S.declaration_by_name(n)
    except:
        return 'gray'
    
    def is_relationship(n):
        while n:
            if n.name() == 'IfcRelationship':
                return True
            n = n.supertype()
    
    return 'yellow' if is_relationship(i) else 'dodgerblue'


def transform_graph(current_entity, graph_data, only_urls=False):
    graphs = pydot.graph_from_dot_data(graph_data)
    graph = graphs[0]
    
    all_nodes = []
    if len(graph.get_subgraphs()):
        for subgraph in graph.get_subgraphs():
            for node in subgraph.get_nodes():
                all_nodes.append(node)
    elif len(graph.get_nodes()):
        for node in graph.get_nodes():
            all_nodes.append(node)
            
    for n in all_nodes:
        if not only_urls:
            n.set('fillcolor', get_node_colour(n.get_name()))
            if n.get_name() == current_entity:
                n.set('color', 'red')
            n.set('shape', 'box')
            n.set('style', 'filled')
        n.set('URL',  url_for('resource', resource=n.get_name(), _external=True))
        
    return graph.to_string()


def process_graphviz(current_entity, md):
    def is_figure(s):
        if 'dot_figure' in s:
            return 1
        elif 'dot_inheritance' in s:
            return 2
        else:
            return 0
        
    graphviz_code = filter(is_figure, re.findall('```(.*?)```', md, re.S))
    
    for c in graphviz_code:
        hash = hashlib.sha256(c.encode('utf-8')).hexdigest()
        fn = os.path.join('svgs', current_entity + "_" + hash+'.dot')
        c2 = transform_graph(current_entity, c, only_urls=is_figure(c) == 2)
        with open(fn, "w") as f:
            f.write(c2)
        md = md.replace("```%s```" % c, '![](/svgs/%s_%s.svg)' % (current_entity, hash))
        subprocess.call(["dot", "-O", "-Tsvg", fn])
    
    return md    
    
"""
@app.route('/svgs/<entity>/<hash>.svg')
def get_svg(entity, hash):
    return send_from_directory('svgs', entity + "_" + hash + '.dot.svg');
"""

@app.route(make_url('figures/<fig>'))
def get_figure(fig):
    return send_from_directory('data/docs/figures', fig)

@app.route(make_url('lexical/<resource>.htm'))
def resource(resource):
    try:
        idx = entity_names.index(resource) + 1
    except:
        abort(404)
    
    package = entity_to_package.get(resource)
    if not package:
        abort(404)
    
    md = None    
    md_root = "data/docs/schemas"
    for category in os.listdir(md_root):
        for module in os.listdir(os.path.join(md_root, category)):
            if module == package:
                md = os.path.join("data/docs/schemas", category, module, "Entities", resource + ".md")
                
    if not md:
        abort(404)
        
    with open(md, 'r', encoding='utf-8') as f:
    
        mdc = f.read()
    
        mdc += '\n\nEntity inheritance\n--------\n\n```' + generate_inheritance_graph(resource) + '```'
    
        html = markdown.markdown(
            process_graphviz(resource, mdc),
            extensions=['tables', 'fenced_code'])
        
        first = True
        
        soup = BeautifulSoup(html)
        
        # First h1 is handled by the template
        soup.find('h1').decompose()
        
        hs = []
        # Renumber the headings
        for i in list(range(7))[::-1]:
            for h in soup.findAll('h%d' % i):
                h.name = 'h%d' % (i + 2)
                hs.append(h)
                
        # Change svg img references to embedded svg
        # because otherwise URLS are not interactive
        for img in soup.findAll("img"):
            if img['src'].endswith('.svg'):
                print(img['src'].split('/')[-1].split('.')[0])
                entity, hash = img['src'].split('/')[-1].split('.')[0].split('_')
                svg = BeautifulSoup(open(os.path.join('svgs', entity + "_" + hash + '.dot.svg')))
                img.replaceWith(svg.find('svg'))
        
        html = str(soup)
        
        return render_template('entity.html', navigation=navigation_entries, content=html, number=idx, entity=resource, path=md[5:])

@app.route(make_url('listing'))
@app.route('/')
def listing():
    items = [{'number': (i + 1), 'url': url_for('resource', resource=n), 'title': n} for i, n in enumerate(entity_names)]
    return render_template('list.html', navigation=navigation_entries, items=items)
    
@app.route(make_url('chapter-<n>/'))
def chapter(n):
    try: n = int(n)
    except: pass
    
    md_root = "data/docs/schemas"
    t = chapter_lookup(number=n).get('title')
    cat = t.split(" ")[0].lower()
    
    fn = os.path.join(md_root, cat, "README.md")
    html = markdown.markdown(open(fn).read())
    soup = BeautifulSoup(html)
    # First h1 is handled by the template
    soup.find('h1').decompose()
    html = str(soup)
    
    subs = sorted(d for d in os.listdir(os.path.join(md_root, cat)) if os.path.isdir(os.path.join(md_root, cat, d)))
    
    return render_template('chapter.html', navigation=navigation_entries, content=html, path=fn[5:], title=t, number=n, subs=subs)

@app.route(make_url('<name>/content.html'))
def schema(name):
    md_root = "data/docs/schemas"
    matches = [d for d in glob.glob(os.path.join(md_root, "**"), recursive=True) if os.path.isdir(d) and d.lower().endswith(name)]
    if not matches: abort(404)
    
    t = matches[0].split(os.sep)[-1]
    parent = sorted(os.listdir(os.path.dirname(matches[0])))
    n1 = chapter_lookup(cat=matches[0].split(os.sep)[-2]).get('number')
    n2 = parent.index(t) + 1
    n = "%d.%d" % (n1, n2)
    fn = os.path.join(matches[0], "README.md")
    html = markdown.markdown(open(fn).read())
    soup = BeautifulSoup(html)
    # First h1 is handled by the template
    soup.find('h1').decompose()
    html = str(soup)

    subs = []

    return render_template('chapter.html', navigation=navigation_entries, content=html, path=fn[5:], title=t, number=n, subs=subs)

@app.route('/search', methods=['GET', 'POST'])
def search():
    matches = []
    query = ''
    if request.method == 'POST' and request.form['query']:
        solr = pysolr.Solr('http://localhost:8983/solr/ifc')
        query = request.form['query']
        results = solr.search('body:(%s)' % query, **{'hl':'on', 'hl.fl':'body'})
        h = results.highlighting
        def format(s):
            return re.sub(r'[^\w\s<>/]', '', s)
        matches = [{
            'url': url_for('resource', resource=r['title'][0]), 
            'match': format(h[r['id']]['body'][0]),
            'title': r['title'][0]
        } for r in list(results)[0:10]]
    return render_template('search.html', navigation=navigation_entries, matches=matches, query=query)
