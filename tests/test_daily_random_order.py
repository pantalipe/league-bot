import random
import unittest
from league_bot.slayer.plan import DEFAULT_MACROS, ordered_macros, ACTIVATIONS, REPEATED_MACROS

class DailyRandomOrderTests(unittest.TestCase):
    def test_seeded_orders_vary_but_always_preserve_dependencies(self):
        orders=[]
        for seed in range(30):
            order=ordered_macros(DEFAULT_MACROS,random.Random(seed))
            self.assertCountEqual(order,DEFAULT_MACROS)
            self.assertEqual(set(order[:2]),set(REPEATED_MACROS))
            self.assertEqual(order[-1],'collect_finished_dailys')
            for activation in ACTIVATIONS:
                for mission in ('cubo_de_melhora','cave_treinoxp'):
                    self.assertLess(order.index(activation),order.index(mission))
            self.assertLess(order.index('refinamento_skill'),order.index('refinamento_skill_completed'))
            self.assertLess(order.index('mailbox'),len(order)-1)
            self.assertLess(order.index('collect_familiar'),len(order)-1)
            orders.append(tuple(order))
        self.assertGreater(len(set(orders)),1)

    def test_same_seed_reproduces_the_schedule_for_diagnosis(self):
        self.assertEqual(ordered_macros(DEFAULT_MACROS,random.Random(17)),
                         ordered_macros(DEFAULT_MACROS,random.Random(17)))
