#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check resource-array constraints from the actual dtschema-processed binding.
This projection complements dt_binding_check; it is not full board validation.
"""
import pathlib,subprocess,tempfile,copy,sys
import dtschema,jsonschema
root=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else '.').resolve()
path='Documentation/devicetree/bindings/net/mediatek,net.yaml'
keys={'compatible','clocks','clock-names','resets','reset-names'}
def project(node):
    if not isinstance(node,dict):return node
    result={}
    for k,v in node.items():
        if k=='properties':result[k]={a:copy.deepcopy(b) for a,b in v.items() if a in keys}
        elif k=='required':result[k]=[a for a in v if a in keys]
        elif k in ('if','then','else'):result[k]=project(v)
        elif k=='allOf':result[k]=[project(a) for a in v if '$ref' not in a]
    return result
fail=0
for version in ('base','v1','v2'):
    if version=='v2':text=(root/path).read_text()
    else:text=subprocess.check_output(['git','show',('6797f12ea40e' if version=='base' else 'ba9e2f36dd22')+':'+path],cwd=root,text=True)
    with tempfile.TemporaryDirectory() as d:
        p=pathlib.Path(d)/'mediatek,net.yaml';p.write_text(text)
        s=project(dtschema.DTSchema(str(p)).fixup());v=jsonschema.Draft7Validator(s)
        cases=[('mt7620 single resource',{'compatible':['mediatek,mt7620-eth'],'clocks':[[1]],'clock-names':['fe'],'resets':[[2]],'reset-names':['fe']},version!='base'),
          ('mt7621 full resources',{'compatible':['mediatek,mt7621-eth'],'clocks':[[1],[2]],'clock-names':['ethif','fe'],'resets':[[3],[4],[5]],'reset-names':['fe','gmac','ppe']},True),
          ('mt7621 incomplete resets',{'compatible':['mediatek,mt7621-eth'],'clocks':[[1],[2]],'clock-names':['ethif','fe'],'resets':[[3]],'reset-names':['fe']},False),
          ('rt5350 one clock',{'compatible':['ralink,rt5350-eth'],'clocks':[[1]],'clock-names':['fe']},False)]
        for name,instance,want in cases:
            actual=v.is_valid(instance);ok=actual==want
            print(f'{version}: {"PASS" if ok else "FAIL"} {name}: accepted={actual}, expected={want}')
            if not ok and version!='v1':fail+=1
# v1 failures are required to demonstrate regressions in the previous draft.
raise SystemExit(bool(fail))
