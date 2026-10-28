from dataclasses import replace
from itertools import permutations
import unittest
from research.symmetry_micro_acceptance import load_config,DEFAULT_CONFIG
from research.symmetry_models import build_research_model,without_prefix,groups,ordered_instance,physical_signature

class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config,cls.instances=load_config(DEFAULT_CONFIG)
    def test_all_fixtures_validate_without_solving(self):
        self.assertEqual(len(self.instances),8)
        for inst in self.instances:
            with self.subTest(case=inst.instance_id):
                self.assertLessEqual(len(inst.boxes),5);self.assertLessEqual(inst.container_volume,64)
                self.assertTrue(any(len(g["box_ids"])>1 for g in groups(inst)))
        self.assertEqual(self.config["cases"][3]["manual_predictions"],{"volume":3,"count":2})
    def test_additive_proto_deltas_and_edges_all_cases_both_objectives(self):
        for inst in self.instances:
            for kind in ("volume","count"):
                baseline,meta=build_research_model(inst,variant="M0",objective_kind=kind)
                self.assertEqual(meta["actual_added_prefix_count"],0)
                for variant in ("M1","M2"):
                    with self.subTest(case=inst.instance_id,kind=kind,variant=variant):
                        art,m=build_research_model(inst,variant=variant,objective_kind=kind)
                        a,b=art.model.Proto(),baseline.model.Proto()
                        self.assertEqual(len(a.variables),len(b.variables))
                        self.assertEqual(len(a.constraints)-len(b.constraints),m["actual_added_prefix_count"])
                        self.assertEqual(without_prefix(a).SerializeToString(deterministic=True),
                                         b.SerializeToString(deterministic=True))
                        added=[c for c in a.constraints if c.name.startswith(("selection_prefix_","diagnostic_reverse_prefix_"))]
                        index=m["box_id_to_index"]
                        for c,(first,second) in zip(added,m["actual_prefix_edges"]):
                            self.assertEqual(dict(zip(c.linear.vars,c.linear.coeffs)),
                                             {baseline.selected[index[first]].Index():1,
                                              baseline.selected[index[second]].Index():-1})
                            self.assertEqual(c.linear.domain[0],0)
    def test_count_objective_not_volume(self):
        inst=self.instances[3]
        count,_=build_research_model(inst,variant="M0",objective_kind="count")
        volume,_=build_research_model(inst,variant="M0",objective_kind="volume")
        self.assertEqual(sorted(abs(x) for x in count.model.Proto().objective.coeffs),[1,1,1,1])
        self.assertEqual(sorted(abs(x) for x in volume.model.Proto().objective.coeffs),[1,1,3,3])
    def test_volume_bound_only_one_independent_constraint(self):
        inst=self.instances[1]
        for variant in ("M0","M1","M2"):
            a,_=build_research_model(inst,variant=variant,objective_kind="volume")
            b,_=build_research_model(inst,variant=variant,objective_kind="volume",volume_bound=True)
            self.assertEqual(len(b.model.Proto().constraints),len(a.model.Proto().constraints)+1)
    def test_mixed_type_interleave_has_matched_baselines(self):
        for inst in (self.instances[3],self.instances[7]):
            transformed=ordered_instance(inst,"interleaved")
            self.assertEqual(physical_signature(inst),physical_signature(transformed))
            self.assertEqual(groups(inst),groups(transformed))
            self.assertEqual([b.box_id for b in transformed.boxes],["a0","b0","a1","b1"])
            original,_=build_research_model(inst,variant="M0",objective_kind="volume")
            for variant in ("M0","M1","M2"):
                art,m=build_research_model(inst,variant=variant,objective_kind="volume",order="interleaved")
                base,_=build_research_model(inst,variant="M0",objective_kind="volume",order="interleaved")
                self.assertEqual(without_prefix(art.model.Proto()).SerializeToString(deterministic=True),
                                 base.model.Proto().SerializeToString(deterministic=True))
                self.assertIn("whole_model",m["intervention"])
            self.assertNotEqual(original.model.Proto().SerializeToString(deterministic=True),
                                base.model.Proto().SerializeToString(deterministic=True))
    def test_single_group_index_interleave_is_degenerate(self):
        inst=self.instances[1]
        self.assertEqual(inst.boxes,ordered_instance(inst,"interleaved").boxes)
    def test_group_weight_invariant_and_capacity_signature(self):
        inst=self.instances[7]
        boxes=list(inst.boxes);boxes[0]=replace(boxes[0],weight=999)
        with self.assertRaises(ValueError):groups(replace(inst,boxes=tuple(boxes)))
        self.assertNotEqual(physical_signature(inst),physical_signature(replace(inst,max_total_weight=9)))
        self.assertEqual(len(groups(inst)),2)
    def test_no_new_variant_or_implicit_objective(self):
        for kwargs in (dict(variant="M3",objective_kind="volume"),dict(variant="M0",objective_kind="mass")):
            with self.assertRaises(ValueError):build_research_model(self.instances[0],**kwargs)

class QuotientTests(unittest.TestCase):
    def test_selected_masks_cover_each_k_under_both_chains(self):
        for m in range(1,6):
            masks=[tuple((n>>i)&1 for i in range(m)) for n in range(1<<m)]
            f=[s for s in masks if all(a>=b for a,b in zip(s,s[1:]))]
            r=[s for s in masks if all(a<=b for a,b in zip(s,s[1:]))]
            self.assertEqual(sorted(map(sum,f)),list(range(m+1)))
            self.assertEqual(sorted(map(sum,r)),list(range(m+1)))
            for s in masks:
                orbit={tuple(s[p[j]] for j in range(m)) for p in permutations(range(m))}
                self.assertTrue(orbit.intersection(f));self.assertTrue(orbit.intersection(r))
    def test_prefix_does_not_choose_unique_placement_representative(self):
        from baseline_common import build_solution
        from validate_solution import validate_solution
        _,instances=load_config(DEFAULT_CONFIG);inst=instances[1]
        def witness(xs):
            placements=[{"box_id":box_id,"orientation":"LWH",
                         "position":{"x":x,"y":0,"z":0},
                         "dimensions":{"length":1,"width":1,"height":1}}
                        for box_id,x in zip(("a0","a1"),xs)]
            return build_solution(inst,placements)
        a,b=witness([0,1]),witness([1,0])
        self.assertTrue(validate_solution(inst.raw,a).valid)
        self.assertTrue(validate_solution(inst.raw,b).valid)
        self.assertNotEqual(a,b)
        self.assertEqual({p["box_id"] for p in a["placements"]},{"a0","a1"})
        self.assertEqual({p["box_id"] for p in b["placements"]},{"a0","a1"})
        self.assertEqual(sorted(p["position"]["x"] for p in a["placements"]),
                         sorted(p["position"]["x"] for p in b["placements"]))
