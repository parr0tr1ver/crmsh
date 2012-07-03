# Copyright (C) 2008-2011 Dejan Muhamedagic <dmuhamedagic@suse.de>
# 
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
# 
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
# 
# You should have received a copy of the GNU General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#

import os
import sys
import subprocess
import copy
import xml.dom.minidom
import re
import glob
from userprefs import Options, UserPrefs
from cache import WCache
from vars import Vars, getpwdent
from utils import *
from msg import *

#
# Resource Agents interface (meta-data, parameters, etc)
#
lrmadmin_prog = "lrmadmin"
class RaLrmd(object):
    '''
    Getting information from the resource agents.
    '''
    def __init__(self):
        self.good = self.is_lrmd_accessible()
    def lrmadmin(self, opts, xml = False):
        '''
        Get information directly from lrmd using lrmadmin.
        '''
        l = stdout2list("%s %s" % (lrmadmin_prog,opts))
        if l and not xml:
            l = l[1:] # skip the first line
        return l
    def is_lrmd_accessible(self):
        if not (is_program(lrmadmin_prog) and is_process("lrmd")):
            return False
        return subprocess.call(\
            add_sudo(">/dev/null 2>&1 %s -C" % lrmadmin_prog), \
            shell=True) == 0
    def meta(self, ra_class,ra_type,ra_provider):
        return self.lrmadmin("-M %s %s %s"%(ra_class,ra_type,ra_provider),True)
    def providers(self, ra_type,ra_class = "ocf"):
        'List of providers for a class:type.'
        return self.lrmadmin("-P %s %s" % (ra_class,ra_type),True)
    def classes(self):
        'List of classes.'
        return self.lrmadmin("-C")
    def types(self, ra_class = "ocf", ra_provider = ""):
        'List of types for a class.'
        return self.lrmadmin("-T %s" % ra_class)

class RaOS(object):
    '''
    Getting information from the resource agents (direct).
    '''
    def __init__(self):
        self.good = True
    def meta(self, ra_class,ra_type,ra_provider):
        l = []
        if ra_class == "ocf":
            l = stdout2list("%s/resource.d/%s/%s meta-data" % \
                (os.environ["OCF_ROOT"],ra_provider,ra_type))
        elif ra_class == "stonith":
            l = stdout2list("stonith -m -t %s" % ra_type)
        return l
    def providers(self, ra_type,ra_class = "ocf"):
        'List of providers for a class:type.'
        l = []
        if ra_class == "ocf":
            for s in glob.glob("%s/resource.d/*/%s" % (os.environ["OCF_ROOT"],ra_type)):
                a = s.split("/")
                if len(a) == 7:
                    l.append(a[5])
        return l
    def classes(self):
        'List of classes.'
        return "heartbeat lsb ocf stonith".split()
    def types(self, ra_class = "ocf", ra_provider = ""):
        'List of types for a class.'
        l = []
        prov = ra_provider and ra_provider or "*"
        if ra_class == "ocf":
            l = os_types_list("%s/resource.d/%s/*" % (os.environ["OCF_ROOT"],prov))
        elif ra_class == "lsb":
            l = os_types_list("/etc/init.d/*")
        elif ra_class == "stonith":
            l = stdout2list("stonith -L")
        l = list(set(l))
        l.sort()
        return l

def can_use_lrmadmin():
    from distutils import version
    # after this glue release all users can get meta-data and
    # similar from lrmd
    minimum_glue = "1.0.10"
    glue_ver = get_stdout("%s -v" % lrmadmin_prog, stderr_on = False)
    v_min = version.StrictVersion(minimum_glue)
    v_this = version.StrictVersion(glue_ver)
    return v_this >= v_min or \
        (getpwdent()[0] in ("root",vars.crm_daemon_user))
def ra_if():
    if vars.ra_if:
        return vars.ra_if
    if can_use_lrmadmin():
        vars.ra_if = RaLrmd()
    if not vars.ra_if or not vars.ra_if.good:
        vars.ra_if = RaOS()
    return vars.ra_if

def ra_classes():
    '''
    List of RA classes.
    '''
    if wcache.is_cached("ra_classes"):
        return wcache.retrieve("ra_classes")
    l = ra_if().classes()
    l.sort()
    return wcache.store("ra_classes",l)
def ra_providers(ra_type,ra_class = "ocf"):
    'List of providers for a class:type.'
    id = "ra_providers-%s-%s" % (ra_class,ra_type)
    if wcache.is_cached(id):
        return wcache.retrieve(id)
    l = ra_if().providers(ra_type,ra_class)
    l.sort()
    return wcache.store(id,l)
def ra_providers_all(ra_class = "ocf"):
    '''
    List of providers for a class.
    '''
    id = "ra_providers_all-%s" % ra_class
    if wcache.is_cached(id):
        return wcache.retrieve(id)
    dir = "%s/resource.d" % os.environ["OCF_ROOT"]
    l = []
    for s in os.listdir(dir):
        if os.path.isdir("%s/%s" % (dir,s)):
            l.append(s)
    l.sort()
    return wcache.store(id,l)
def ra_types(ra_class = "ocf", ra_provider = ""):
    '''
    List of RA type for a class.
    '''
    if not ra_class:
        ra_class = "ocf"
    id = "ra_types-%s-%s" % (ra_class,ra_provider)
    if wcache.is_cached(id):
        return wcache.retrieve(id)
    if ra_provider:
        list = []
        for ra in ra_if().types(ra_class):
            if ra_provider in ra_providers(ra,ra_class):
                list.append(ra)
    else:
        list = ra_if().types(ra_class)
    list.sort()
    return wcache.store(id,list)

def get_pe_meta():
    if not vars.pe_metadata:
        vars.pe_metadata = RAInfo("pengine","metadata")
    return vars.pe_metadata
def get_crmd_meta():
    if not vars.crmd_metadata:
        vars.crmd_metadata = RAInfo("crmd","metadata")
        vars.crmd_metadata.set_advanced_params(vars.crmd_advanced)
    return vars.crmd_metadata
def get_stonithd_meta():
    if not vars.stonithd_metadata:
        vars.stonithd_metadata = RAInfo("stonithd","metadata")
    return vars.stonithd_metadata
def get_cib_meta():
    if not vars.cib_metadata:
        vars.cib_metadata = RAInfo("cib","metadata")
    return vars.cib_metadata
def get_properties_meta():
    if not vars.crm_properties_metadata:
        get_pe_meta()
        get_crmd_meta()
        get_cib_meta()
        vars.crm_properties_metadata = copy.deepcopy(vars.crmd_metadata)
        vars.crm_properties_metadata.add_ra_params(vars.pe_metadata)
        vars.crm_properties_metadata.add_ra_params(vars.cib_metadata)
    return vars.crm_properties_metadata
def get_properties_list():
    try:
        return get_properties_meta().params().keys()
    except:
        return []

def prog_meta(prog):
    '''
    Do external program metadata.
    '''
    l = []
    if is_program(prog):
        l = stdout2list("%s metadata" % prog)
    return l
def get_nodes_text(n,tag):
    try:
        node = n.getElementsByTagName(tag)[0]
        for c in node.childNodes:
            if c.nodeType == c.TEXT_NODE:
                return c.data.strip()
    except: return ''

def mk_monitor_name(role,depth):
    depth = depth != "0" and ("_%s" % depth) or ""
    return role and role != "Started" and \
        "monitor_%s%s" % (role,depth) or \
        "monitor%s" % depth
def monitor_name_node(node):
    depth = node.getAttribute("depth") or '0'
    role = node.getAttribute("role")
    return mk_monitor_name(role,depth)
def monitor_name_pl(pl):
    depth = find_value(pl, "depth") or '0'
    role = find_value(pl, "role")
    return mk_monitor_name(role,depth)

class RAInfo(object):
    '''
    A resource agent and whatever's useful about it.
    '''
    ra_tab = "    "  # four horses
    required_ops = ("start", "stop")
    skip_ops = ("meta-data", "validate-all")
    skip_op_attr = ("name", "depth", "role")
    def __init__(self,ra_class,ra_type,ra_provider = "heartbeat"):
        self.advanced_params = []
        self.ra_class = ra_class
        self.ra_type = ra_type
        self.ra_provider = ra_provider
        if not self.ra_provider:
            self.ra_provider = "heartbeat"
        self.ra_node = None
    def ra_string(self):
        return self.ra_class == "ocf" and \
            "%s:%s:%s" % (self.ra_class, self.ra_provider, self.ra_type) or \
            "%s:%s" % (self.ra_class, self.ra_type)
    def error(self, s):
        common_err("%s: %s" % (self.ra_string(), s))
    def warn(self, s):
        common_warn("%s: %s" % (self.ra_string(), s))
    def set_advanced_params(self, l):
        self.advanced_params = l
    def filter_crmd_attributes(self):
        for n in self.ra_node.getElementsByTagName("parameter"):
            if not n.getAttribute("name") in vars.crmd_user_attributes:
                n.parentNode.removeChild(n)
    def add_ra_params(self,ra):
        '''
        Add parameters from another RAInfo instance.
        '''
        try:
            if not self.mk_ra_node() or not ra.mk_ra_node():
                return
        except:
            return
        try:
            params_node = self.doc.getElementsByTagName("parameters")[0]
        except:
            params_node = self.doc.createElement("parameters")
            self.ra_node.appendChild(params_node)
        for n in ra.ra_node.getElementsByTagName("parameter"):
            params_node.appendChild(self.doc.importNode(n,1))
    def mk_ra_node(self):
        '''
        Return the resource_agent node.
        '''
        if self.ra_node:
            return self.ra_node
        meta = self.meta()
        try:
            self.doc = xml.dom.minidom.parseString('\n'.join(meta))
        except:
            self.error("could not parse meta-data: %s" % '\n'.join(meta))
            self.ra_node = None
            return None
        try:
            self.ra_node = self.doc.getElementsByTagName("resource-agent")[0]
        except:
            self.error("meta-data contains no resource-agent element")
            self.ra_node = None
            return None
        if self.ra_class == "stonith":
            self.add_ra_params(get_stonithd_meta())
        return self.ra_node
    def param_type_default(self,n):
        try:
            content = n.getElementsByTagName("content")[0]
            type = content.getAttribute("type")
            default = content.getAttribute("default")
            return type,default
        except:
            return None,None
    def params(self):
        '''
        Construct a dict of dicts: parameters are keys and
        dictionary of attributes/values are values. Cached too.
        '''
        id = "ra_params-%s" % self.ra_string()
        if wcache.is_cached(id):
            return wcache.retrieve(id)
        if not self.mk_ra_node():
            return None
        d = {}
        for pset in self.ra_node.getElementsByTagName("parameters"):
            for c in pset.getElementsByTagName("parameter"):
                name = c.getAttribute("name")
                if not name:
                    continue
                required = c.getAttribute("required")
                unique = c.getAttribute("unique")
                type,default = self.param_type_default(c)
                d[name] = {
                    "required": required,
                    "unique": unique,
                    "type": type,
                    "default": default,
                }
        return wcache.store(id,d)
    def completion_params(self):
        '''
        Extra method for completion, for we want to filter some
        (advanced) parameters out. And we want this to be fast.
        '''
        if not self.mk_ra_node():
            return None
        return [c.getAttribute("name")
            for c in self.ra_node.getElementsByTagName("parameter")
                if c.getAttribute("name")
                and c.getAttribute("name") not in self.advanced_params
        ]
    def actions(self):
        '''
        Construct a dict of dicts: actions are keys and
        dictionary of attributes/values are values. Cached too.
        '''
        id = "ra_actions-%s" % self.ra_string()
        if wcache.is_cached(id):
            return wcache.retrieve(id)
        if not self.mk_ra_node():
            return None
        d = {}
        for pset in self.ra_node.getElementsByTagName("actions"):
            for c in pset.getElementsByTagName("action"):
                name = c.getAttribute("name")
                if not name or name in self.skip_ops:
                    continue
                if name == "monitor":
                    name = monitor_name_node(c)
                d[name] = {}
                for a in c.attributes.keys():
                    if a in self.skip_op_attr:
                        continue
                    v = c.getAttribute(a)
                    if v:
                        d[name][a] = v
        # add monitor ops without role, if they don't already
        # exist
        d2 = {}
        for op in d.keys():
            if re.match("monitor_[^0-9]", op):
                norole_op = re.sub(r'monitor_[^0-9_]+_(.*)', r'monitor_\1', op)
                if not norole_op in d:
                    d2[norole_op] = d[op]
        d.update(d2)
        return wcache.store(id,d)
    def reqd_params_list(self):
        '''
        List of required parameters.
        '''
        d = self.params()
        if not d: return []
        return [x for x in d if d[x]["required"] == '1']
    def param_default(self,pname):
        '''
        Parameter's default.
        '''
        d = self.params()
        try: return d[pname]["default"]
        except: return None
    def unreq_param(self, p):
        '''
        Allow for some exceptions.
        
        - the rhcs stonith agents sometimes require "action" (in
          the meta-data) and "port", but they're automatically
          supplied by stonithd
        '''
        if self.ra_class == "stonith" and \
            (self.ra_type.startswith("rhcs/") or \
            self.ra_type.startswith("fence_")):
            if p in ("action", "port"):
                return True
        return False
    def sanity_check_params(self, id, pl, existence_only = False):
        '''
        pl is a list of (attribute,value) pairs.
        - are all required parameters defined
        - do all parameters exist
        '''
        rc = 0
        d = {}
        for p,v in pl:
            d[p] = v
        if not existence_only:
            for p in self.reqd_params_list():
                if self.unreq_param(p):
                    continue
                if p not in d:
                    common_err("%s: required parameter %s not defined" % (id,p))
                    rc |= user_prefs.get_check_rc()
        for p in d:
            if p not in self.params():
                common_err("%s: parameter %s does not exist" % (id,p))
                rc |= user_prefs.get_check_rc()
        return rc
    def get_adv_timeout(self, op, node = None):
        if node and op == "monitor":
            name = monitor_name_node(node)
        else:
            name = op
        try:
            return self.actions()[name]["timeout"]
        except:
            return None
    def sanity_check_ops(self, id, ops, default_timeout):
        '''
        ops is a list of operations
        - do all operations exist
        - are timeouts sensible
        '''
        rc = 0
        n_ops = {}
        for op in ops:
            n_op = op[0] == "monitor" and monitor_name_pl(op[1]) or op[0]
            n_ops[n_op] = {}
            for p,v in op[1]:
                if p in self.skip_op_attr:
                    continue
                n_ops[n_op][p] = v
        for req_op in self.required_ops:
            if req_op not in n_ops:
                n_ops[req_op] = {}
        intervals = {}
        for op in n_ops:
            if op not in self.actions():
                common_warn("%s: action %s not advertised in meta-data, it may not be supported by the RA" % (id,op))
                rc |= 1
            if "interval" in n_ops[op]:
                v = n_ops[op]["interval"]
                v_msec = crm_msec(v)
                if op in ("start", "stop") and v_msec != 0:
                    common_warn("%s: Specified interval for %s is %s, it must be 0" %(id,op,v))
                    rc |= 1
                if op.startswith("monitor") and v_msec != 0:
                    if v_msec not in intervals:
                        intervals[v_msec] = 1
                    else:
                        common_warn("%s: interval in %s must be unique" % (id, op))
                        rc |= 1
            try:
                adv_timeout = self.actions()[op]["timeout"]
            except:
                continue
            if "timeout" in n_ops[op]:
                v = n_ops[op]["timeout"]
                timeout_string = "specified timeout"
            else:
                v = default_timeout
                timeout_string = "default timeout"
            if crm_msec(v) < 0:
                continue
            if crm_time_cmp(adv_timeout,v) > 0:
                common_warn("%s: %s %s for %s is smaller than the advised %s" % \
                    (id,timeout_string,v,op,adv_timeout))
                rc |= 1
        return rc
    def meta(self):
        '''
        RA meta-data as raw xml.
        '''
        id = "ra_meta-%s" % self.ra_string()
        if wcache.is_cached(id):
            return wcache.retrieve(id)
        if self.ra_class in vars.meta_progs:
            l = prog_meta(self.ra_class)
        else:
            l = ra_if().meta(self.ra_class,self.ra_type,self.ra_provider)
        return wcache.store(id, l)
    def meta_pretty(self):
        '''
        Print the RA meta-data in a human readable form.
        '''
        if not self.mk_ra_node():
            return ''
        l = []
        title = self.meta_title()
        l.append(title)
        longdesc = get_nodes_text(self.ra_node,"longdesc")
        if longdesc:
            l.append(longdesc)
        if self.ra_class != "heartbeat":
            params = self.meta_parameters()
            if params:
                l.append(params.rstrip())
        actions = self.meta_actions()
        if actions:
            l.append(actions)
        return '\n\n'.join(l)
    def get_shortdesc(self,n):
        name = n.getAttribute("name")
        shortdesc = get_nodes_text(n,"shortdesc")
        longdesc = get_nodes_text(n,"longdesc")
        if shortdesc and shortdesc not in (name,longdesc,self.ra_type):
            return shortdesc
        return ''
    def meta_title(self):
        s = self.ra_string()
        shortdesc = self.get_shortdesc(self.ra_node)
        if shortdesc:
            s = "%s (%s)" % (shortdesc,s)
        return s
    def meta_param_head(self,n):
        name = n.getAttribute("name")
        if not name:
            return None
        s = name
        if n.getAttribute("required") == "1":
            s = s + "*"
        type,default = self.param_type_default(n)
        if type and default:
            s = "%s (%s, [%s])" % (s,type,default)
        elif type:
            s = "%s (%s)" % (s,type)
        shortdesc = self.get_shortdesc(n)
        s = "%s: %s" % (s,shortdesc)
        return s
    def format_parameter(self,n):
        l = []
        head = self.meta_param_head(n)
        if not head:
            self.error("no name attribute for parameter")
            return ""
        l.append(head)
        longdesc = get_nodes_text(n,"longdesc")
        if longdesc:
            longdesc = self.ra_tab + longdesc.replace("\n","\n"+self.ra_tab) + '\n'
            l.append(longdesc)
        return '\n'.join(l)
    def meta_parameter(self,param):
        if not self.mk_ra_node():
            return ''
        l = []
        for pset in self.ra_node.getElementsByTagName("parameters"):
            for c in pset.getElementsByTagName("parameter"):
                if c.getAttribute("name") == param:
                    return self.format_parameter(c)
    def meta_parameters(self):
        if not self.mk_ra_node():
            return ''
        l = []
        for pset in self.ra_node.getElementsByTagName("parameters"):
            for c in pset.getElementsByTagName("parameter"):
                s = self.format_parameter(c)
                if s:
                    l.append(s)
        if l:
            return "Parameters (* denotes required, [] the default):\n\n" + '\n'.join(l)
    def meta_action_head(self,n):
        name = n.getAttribute("name")
        if not name:
            return ''
        if name in self.skip_ops:
            return ''
        if name == "monitor":
            name = monitor_name_node(n)
        s = "%-13s" % name
        for a in n.attributes.keys():
            if a in self.skip_op_attr:
                continue
            v = n.getAttribute(a)
            if v:
                s = "%s %s=%s" % (s,a,v)
        return s
    def meta_actions(self):
        l = []
        for aset in self.ra_node.getElementsByTagName("actions"):
            for c in aset.getElementsByTagName("action"):
                s = self.meta_action_head(c)
                if s:
                    l.append(self.ra_tab + s)
        if l:
            return "Operations' defaults (advisory minimum):\n\n" + '\n'.join(l)

def get_ra(node):
    ra_type = node.getAttribute("type")
    ra_class = node.getAttribute("class")
    ra_provider = node.getAttribute("provider")
    return RAInfo(ra_class,ra_type,ra_provider)

#
# resource type definition
#
def ra_type_validate(s, ra_class, provider, rsc_type):
    '''
    Only ocf ra class supports providers.
    '''
    if not rsc_type:
        common_err("bad resource type specification %s"%s)
        return False
    if ra_class == "ocf":
        if not provider:
            common_err("provider could not be determined for %s"%s)
            return False
    else:
        if provider:
            common_warn("ra class %s does not support providers"%ra_class)
            return True
    return True
def disambiguate_ra_type(s):
    '''
    Unravel [class:[provider:]]type
    '''
    l = s.split(':')
    if not l or len(l) > 3:
        return ["","",""]
    if len(l) == 3:
        return l
    elif len(l) == 2:
        ra_class,ra_type = l
    else:
        ra_class = "ocf"
        ra_type = l[0]
    ra_provider = ''
    if ra_class == "ocf":
        pl = ra_providers(ra_type,ra_class)
        if pl and len(pl) == 1:
            ra_provider = pl[0]
        elif not pl:
            ra_provider = 'heartbeat'
    return ra_class,ra_provider,ra_type

wcache = WCache.getInstance()
vars = Vars.getInstance()
# vim:ts=4:sw=4:et:
