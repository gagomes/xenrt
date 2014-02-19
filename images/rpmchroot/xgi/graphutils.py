#!/usr/bin/env python
# (c) XenSource 2005

import copy
    
class GraphNode:
    def __init__(self, name, adj = None):
        if adj == None: adj = []
        
        self.name = name
        self.adj = adj
        self.colour = 0
        self.discoverytime = 0
        self.finishtime = 0
        self.predecessor = None
        
    def __deepcopy__(self, memo):
        n = GraphNode(self.name)
        n.name = self.name
        n.adj = self.adj[:]
        n.colour = self.colour
        n.discoverytime = self.discoverytime
        n.finishtime = self.finishtime
        n.predecessor = self.predecessor
        return n

class Graph:
    def __init__(self):
        self.nodes = []

    def addNodes(self, *ns):
        for n in ns:
            assert isinstance(n, GraphNode)
            self.nodes.append(n)

    # Depth-first search a graph, filling in each node's
    # discoverytime, finishtime and predecessor fields.
    #
    # Returns a list of forrests encountered.
    def dfs_search(self):
        def dfs_visit(x, time):
            visited = [ x ]
            
            x.colour = 1
            time = time + 1
            x.discoverytime = time
            for node in x.adj:
                if node.colour == 0:
                    node.predecessor = x
                    (time, nowvisited) = dfs_visit(node, time)
                    visited += nowvisited
            x.colour = 2
            time = time + 1
            x.finishtime = time
            return (time, visited)

        for x in self.nodes:
            x.colour = 0
            x.pi = 0

        time = 0
        forrests = []
        for x in self.nodes:
            visited = []
            if x.colour == 0:
                (time, visited) = dfs_visit(x, time)
            if len(visited) > 0:
                forrests = forrests + [ visited ]

        return forrests

    def transpose(self):
        rv = copy.deepcopy(self)
        mapping = {}
        
        for x in range(len(rv.nodes)):
            rv.nodes[x].adj = []
            mapping[self.nodes[x]] = rv.nodes[x]

        for ni in range(len(self.nodes)):
            for adj in self.nodes[ni].adj:
                mapping[adj].adj.append(rv.nodes[ni])

        return rv

    # Get a list of strongly connected components
    def scc(self):
        self.dfs_search()
        transp = self.transpose()
        transp.nodes.sort(lambda x1, x2: cmp(x2.finishtime, x1.finishtime))
        return transp.dfs_search()

    # Get the components graph
    def gscc(self):
        comps = self.scc()
        compnodes = map(lambda x: GraphNode(map(lambda y: y.name, x)), comps)

        def in_same_scc(comps, v1, v2):
            for x in comps:
                if v1 in x and v2 in x:
                    return True
            return False

        def get_scc(compnodes, v):
            for x in compnodes:
                for v2 in x.name:
                    if v2 == v:
                        return x
            return None

        def union(list1, list2):
            for x in list1:
                if x in list2:
                    list2.remove(x)
            return list1 + list2

        newgraph = Graph()
        for x in self.nodes:
            node = get_scc(compnodes, x.name)
            newadj = map(lambda x: get_scc(compnodes, x.name), x.adj)
            if node in newadj:
                newadj.remove(node)
            node.adj = union(node.adj, newadj)
            if node not in newgraph:
                newgraph.addNodes(node)

        return newgraph

    def __iter__(self):
        return self.nodes.__iter__()

def main():
    """ quick test suite """
    g = Graph()
    a = GraphNode("a")
    b = GraphNode("b")
    c = GraphNode("c")
    d = GraphNode("d")
    a.adj = [ b ]
    b.adj = [ c ]
    c.adj = [ b,d ]

    g.addNodes(a, b, c, d)

    scc_graph = g.gscc()
    print map(lambda x: x.name, scc_graph.nodes)
    print map(lambda x: map(lambda y: y.name, x.adj), scc_graph.nodes)
    
if __name__ == "__main__":
    main()

