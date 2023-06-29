from tqdm import tqdm
import pandas as pd
import numpy as np
import time
import random
import click

from info.device_config import config
from info.device_arg import device_arg
from info.adj_list import *
from utils import *

import warnings
warnings.filterwarnings("ignore")


### functions to load all data ###

def get_capabilities(result):
    capabilities = list(result.target.value_counts().keys())
    return capabilities

def get_arguments(result, cap_value):
    arguments = result.argument.to_dict()
    for arg in arguments:
        if arguments[arg]:
            try:
                arguments[arg] = cap_value[result.loc[arg].target][0]
            except:
                argument = []
                for a in range(len(result.loc[arg].target)):
                    argument.append(list(cap_value[(result.loc[arg].target[a],)][0]))
                arguments[arg] = tuple(set(sum(argument, [])))
    return arguments

def get_condition(result, capabilities):
    dependencies = {c:{} for c in capabilities}
    for i in range(len(result)):
        dependencies[result.iloc[i].target].update({result.iloc[i].name:result.iloc[i].dependencies})
    return dependencies

def get_cap_ord(result, capabilities):
    dep_list = sum([[list(k.keys())[0], j] if len(k)>0 else [None, j] for j,k in zip(result.target.tolist(), result.dependencies.tolist())], [])
    cap_ord = []
    for i in dep_list:
        if i and i not in cap_ord:
            cap_ord.append(i)
    return cap_ord[::-1]


### Bulid Models ###
    
def reg_cls(calc, info, encoders, cap_value, i):
    if info.types[i] == 'c':
        return (encoders[info.target[i]].inverse_transform([calc])[0])
    if info.types[i] == 'r':
        return (get_closest(cap_value[(info.target[i].split('+')[-1],)][0], calc))
    
def encode(cmd, target, encoders, arguments, cap_value, prev, cur, arg=-1):
    encode_prev = []
    for i in range(len(prev)):
        if type(prev[i]) == str:
            encoder = encoders[target[i]]
            num = len(encoder.classes_)
            encode_prev.append(np.eye(num)[encoder.transform([prev[i]])[0]].tolist())
        else:
            if target[cur] in encoders:
                encode_prev.append([(prev[i]-cap_value[(target[i],)][0][0])/(cap_value[(target[i],)][0][-1]- cap_value[(target[i],)][0][0])])
            else:
                encode_prev.append([prev[i]])
    encode_prev = sum(encode_prev, [])
    if arg != -1:
        if type(arg) == str:
            encoder = encoders[cmd]
            num = len(encoder.classes_)
            arg = np.eye(num)[encoder.transform([arg])[0]].tolist()
        else:
            if target[cur] in encoders:
                arg = [(arg-arguments[cmd.split('>')[0]][0])/(arguments[cmd.split('>')[0]][-1]- arguments[cmd.split('>')[0]][0])]
            else:
                arg = [arg]
        return [encode_prev+arg]
    else:
        return [encode_prev]

def model(info, encoders, cap_value, arguments):
        if info.argument:
            return lambda prev, arg: tuple([reg_cls(info.model[i].predict(encode(info.name, info.target, encoders, arguments, cap_value, prev,i, arg,)), info, encoders, cap_value, i) for i in range(len(info.model))])
        else:
            return lambda prev: tuple([reg_cls(info.model[i].predict(encode(info.name, info.target, encoders, arguments, cap_value, prev, i)), info, encoders, cap_value, i) for i in range(len(info.model))])

def get_models(result, capabilities, cap_value, encoders, arguments):
    models = {k:{} for k in capabilities}
    for cmd in result.index:
        info = result.loc[cmd]
        models[info['target']][cmd] = model(info, encoders, cap_value, arguments)
    return models


### Create random states for planning ###

def random_state(capabilities, cap_value):
    state = {}
    for cap in capabilities:
        if len(cap)>1:
            org_cap = tuple(i.split('+')[-1] for i in cap)
            val = [cap_value[(c,)][0][0] for c in org_cap]
            pick = random.randint(0, len(cap)-1)
            val[pick] = random.sample(cap_value[(org_cap[pick],)][0], 1)[0]
        else:
            val =  random.sample(cap_value[cap][0], 1)
        state[cap] = tuple(val)
    return state

def ungroup(state):
    for cap in list(state.keys()):
        if len(cap) > 1:
            for i in range(len(cap)):
                state.update({(cap[i],):(state[cap][i],)})
            state.pop(cap)
    return state

def group(state, capabilities):
    for cap in capabilities:
        if len(cap)>1:
            val = tuple()
            for i in range(len(cap)):
                if type(state[(cap[i],)]) != tuple:
                    state[(cap[i],)] = (state[(cap[i],)],)
                val += state[(cap[i],)]
                state.pop((cap[i],))
            state[cap] = val
    return state

def random_states(capabilities, cap_value, level, adj_list):
    prev = random_state(capabilities, cap_value)
    next = ungroup(prev.copy())
    for i in range(level):
        next = random.sample([i for i in adj_list(next)], 1)[0][0]
    next = group(next, capabilities)
    return prev, next

class done(Exception): pass
def set_cap(state, cap, val, models, condition, arguments):
    if state[cap] == val:
        return state, [], 1, 1
    q = [state[cap]]
    prevcmd = {state[cap]:None}
    cmds = list(models[cap].keys())
    maxq = 1
    visited = 0
    try:
        while len(q) > 0:
            curr = q.pop(0)
            for cmd in cmds:
                if cap in condition[cap][cmd] and curr not in condition[cap][cmd][cap]:
                    continue
                if not arguments[cmd.split('>')[0]]:
                    vnext = models[cap][cmd](curr)
                    visited += 1
                    if vnext not in prevcmd:
                        prevcmd[vnext] = (curr, cmd, None)
                        maxq += 1
                        q.append(vnext)
                    if vnext == val:
                        raise done
                else:
                    args = arguments[cmd.split('>')[0]]
                    if 'arguments' in condition[cap][cmd]:
                        args = condition[cap][cmd]['arguments']
                    for arg in args:
                        visited += 1
                        vnext = models[cap][cmd](curr, arg)
                        if vnext not in prevcmd:
                            prevcmd[vnext] = (curr, cmd, arg)
                            maxq += 1
                            q.append(vnext)
                        if vnext == val:
                            raise done
    except done:
        pass
    curr = prevcmd[val]
    path = []
    while curr is not None:
        path.insert(0, (curr[1], curr[2]))
        curr = prevcmd[curr[0]]
    plan = []
    currstate = state
    for cmd, arg in path:
        for depcap in condition[cap][cmd]:
            if depcap == ('arguments',):
                continue
            if currstate[depcap] not in condition[cap][cmd][depcap]:
                setting = set_cap(currstate, depcap, condition[cap][cmd][depcap][0], models, condition, arguments)
                currstate = setting[0]
                plan += setting[1]
                maxq = max(maxq, setting[2])
                visited += setting[3]
        plan += [(cmd, arg)]
        if arg is None:
            currstate[cap] = models[cap][cmd](currstate[cap])
        else:
            currstate[cap] = models[cap][cmd](currstate[cap], arg)
    return currstate, plan, maxq, visited

def smartAID(curr, query, cap_ord, pack):
    condition, cap_ord, models, arguments = pack
    curr_state = curr
    rtn = []
    maxq = 0
    visited = 0
    for cap in cap_ord:
        curr_state, plan, mq, vs = set_cap(curr_state, cap, query[cap], models, condition, arguments)
        rtn += plan
        maxq = max(maxq, mq)
        visited += vs
    return (None, rtn), maxq, visited

def state_hash(state):
    ststr = ''
    for k in sorted(state):
        ststr += f'{k}:{state[k]}|'
    return ststr
def state_compare(st1, st2):
    if state_hash(st1) == state_hash(st2):
        return True
    else:
        return False
def state_unhash(ststr):
    st = {}
    tokens = ststr.split('|')
    for t in tokens[:-1]:
        kv = t.split(':')
        st[eval(kv[0])] = eval(kv[1])
    return st
    
def backtrace(parent, command, start, end):
    path = [end]
    plan = []
    while path[-1] != start:
        plan.append(command[path[-1]])
        path.append(parent[path[-1]])
    path.reverse()
    plan.reverse()
    return path, plan

def BFS(start, query, adj_list, condtion=False):
    parent = {}
    command = {}
    queue = []
    chk = set([])
    queue.append(state_hash(start))
    chk.add(state_hash(start))
    visited_num = 0
    memory_num = 0
    if state_hash(start) == state_hash(query):
        return ([state_hash(start)], []), 1, 1
    while queue:
        node = queue.pop(0)
        chk.add(node)
        # if node == state_hash(query):
        #     return backtrace(parent, command, state_hash(start), state_hash(query))
        for adj, cmd in adj_list(state_unhash(node)):
            visited_num += 1
            adjhash = state_hash(adj)
            if adjhash in chk:
                continue
            if adjhash in queue:
                continue
            elif adjhash == state_hash(query):
                parent[adjhash] = node
                command[adjhash] = cmd
                return backtrace(parent, command, state_hash(start), state_hash(query)), memory_num, visited_num
            else:
                parent[adjhash] = node
                command[adjhash] = cmd
                queue.append(adjhash)
                memory_num += 1

import heapq
class DijkstraHeap(list):
    def __init__(self, init=None):
        self.visited = dict()
        if init is not None:
            self.insert(init)
    def insert(self, item):
        if item[1] not in self.visited:
            heapq.heappush(self, item)
    def memory(self):
        return len(self)+len(self.visited)
    def pop(self):
        while self and self[0][1] in self.visited:
            heapq.heappop(self)
        if self:
            next_item = heapq.heappop(self)
            self.visited[next_item[1]] = next_item[2]
            return next_item
            
def Astar(start, query, adj_list, condition=False):
    hash_start = state_hash(start)
    hash_query = state_hash(query)
    frontier = DijkstraHeap((hamming(hash_start, hash_query), hash_start, None))
    memory_num = 0
    visited_num = 0
    while frontier:
        current = frontier.pop()
        memory_num = max(memory_num, frontier.memory())
        if current[1] == hash_query:
            state_seq = [hash_query]
            action_seq = []
            n = hash_query
            while frontier.visited[n] != None:
                state_seq.append(frontier.visited[n][0])
                action_seq.append(frontier.visited[n][1])
                n = frontier.visited[n][0]
            state_seq.reverse()
            action_seq.reverse()
            return (state_seq, action_seq), memory_num, visited_num
        for adj, cmd in adj_list(state_unhash(current[1])):
            visited_num += 1
            adjhash = state_hash(adj)
            cost = current[0] - hamming(current[1], hash_query)
            new_cost = cost + 1 + hamming(adjhash, hash_query)
            frontier.insert((new_cost, adjhash, (current[1], cmd)))

def hamming(st1, st2):
    dist = 0
    tokens1 = st1.split('|')
    tokens2 = st2.split('|')
    for t1, t2 in zip(tokens1, tokens2):
        try:
            if t1.split(':')[1] != t2.split(':')[1]:
                dist+=1
        except:
            continue
    return dist

def plan(model, num, level, cap_value, capabilities, adj_list, pack=False):
    plans = []
    for i in tqdm(range(num)):
        prev, next = random_states(capabilities, cap_value, level, adj_list)
        
        if not pack:
            prev, next = ungroup(prev), ungroup(next)     

        prev_df = pd.DataFrame({str(i): [prev[i]] for i in prev})
        start = time.time()
        plan, memory_num, visited_num = model(prev, next, adj_list, pack)
        end = time.time()
        
        plan = pd.DataFrame({'cmds': [plan[1]]})
        plan['length'] = plan.cmds.apply(len)
        plan['time'] = end-start
        plan['memory_num'] = memory_num
        plan['visited_num'] = visited_num
        
        plans.append(pd.concat([prev_df, pd.DataFrame({str(i): [next[i]] for i in next}), plan], axis=1, keys=['prev', 'next', 'plan']))

    plans = pd.concat(plans).reset_index(drop=True)
    stat = plans['plan'][['length', 'time', 'memory_num', 'visited_num']].describe()
    print(stat)
    return plans, stat

@click.command()
@click.option('--name', type=str, default='smartAID')
@click.option('--device', type=str, default='bulb')
@click.option('--distance', type=int, default=-1)
@click.option('--num', type=int, default=1000)
@click.option('--save', type=bool, default=True)
def main(name, device, distance, num, save):

    result = load_data('./smartAID_models/'+device+'_trained')
    encoders = load_data('./smartAID_models/'+device+'_encoders')
    cap_value = config[device]

    if device == 'bulb':
        adj_list = bulb_adj_list
    elif device == 'TV':
        adj_list = tv_adj_list
    elif device == 'airPurifier':
        adj_list = airPurifier_adj_list
    elif device == 'robot':
        adj_list = robotcleaner_adj_list

    capabilities = get_capabilities(result)

    if name == 'smartAID':
        condition = get_condition(result, capabilities)
        cap_ord = get_cap_ord(result, capabilities)
        arguments = device_arg[device]
        models = get_models(result, capabilities, cap_value, encoders, arguments)
        pack = (condition, cap_ord, models, arguments)
        model = smartAID
    else:
        pack = False
        if name == 'BFS':
            model = BFS
        elif name == 'Astar':
            model = Astar
    
    if distance == -1:
        distance = range(1, 6)
    else:
        distance = [distance]
    
    print("\n=====", name, "======\n")
    
    for d in distance:
        print("["+device.upper()+"]", 'DISTANCE', d)
        plans, stats = plan(model, num, d, cap_value, capabilities, adj_list, pack)
        if save:
            plans.to_csv('./plan_results/'+name+'/'+device+'_plans'+'_D'+str(d)+'.csv')
            stats.to_csv('./plan_results/'+name+'/'+device+'_stats'+'_D'+str(d)+'.csv')
        print()

if __name__ == '__main__':
    main()