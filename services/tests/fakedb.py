"""Minimal in-memory DynamoDB table: just the operations Hivemate uses, with the same conditional-write behaviour."""
import re
from decimal import Decimal

from botocore.exceptions import ClientError


def _fail(op="PutItem"):
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "cond"}}, op)


def _norm(v):
    if isinstance(v, float):
        return Decimal(str(v))
    return v


class FakeTable:
    def __init__(self):
        self.items: dict[tuple, dict] = {}

    # --- helpers
    def _get(self, pk, sk):
        return self.items.get((pk, sk))

    def seed(self, *items):
        for i in items:
            self.items[(i["PK"], i["SK"])] = dict(i)

    # --- API
    def get_item(self, Key, **_):
        it = self._get(Key["PK"], Key["SK"])
        return {"Item": dict(it)} if it else {}

    def put_item(self, Item, ConditionExpression=None, **_):
        if ConditionExpression and "attribute_not_exists" in ConditionExpression and (Item["PK"], Item["SK"]) in self.items:
            raise _fail()
        self.items[(Item["PK"], Item["SK"])] = dict(Item)

    def delete_item(self, Key, **_):
        self.items.pop((Key["PK"], Key["SK"]), None)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames=None, ExpressionAttributeValues=None, ConditionExpression=None, **_):
        names, vals = ExpressionAttributeNames or {}, ExpressionAttributeValues or {}
        it = self._get(Key["PK"], Key["SK"])
        for cond in [c.strip() for c in (ConditionExpression or "").split(" AND ") if c.strip()]:
            if cond == "attribute_exists(PK)":
                if it is None:
                    raise _fail("UpdateItem")
                continue
            m = re.fullmatch(r"(#\w+|\w+) = (:\w+)", cond)
            assert m, f"fake table cannot parse condition {cond!r}"
            attr = names.get(m.group(1), m.group(1))
            if it is None or it.get(attr) != _norm(vals[m.group(2)]):
                raise _fail("UpdateItem")
        if it is None:
            it = {"PK": Key["PK"], "SK": Key["SK"]}
            self.items[(Key["PK"], Key["SK"])] = it
        for clause in re.split(r"\s(?=(?:SET|REMOVE|ADD)\s)", UpdateExpression):
            kind, _, rest = clause.partition(" ")
            for part in [p.strip() for p in rest.split(",")]:
                if kind == "SET":
                    a, v = [x.strip() for x in part.split(" = ")]
                    it[names.get(a, a)] = _norm(vals[v])
                elif kind == "REMOVE":
                    it.pop(names.get(part, part), None)
                elif kind == "ADD":
                    a, v = part.split(" ")
                    it[names.get(a, a)] = it.get(names.get(a, a), 0) + _norm(vals[v])

    @staticmethod
    def _leaves(cond):
        e = cond.get_expression()
        if e["operator"] == "AND":
            for v in e["values"]:
                yield from FakeTable._leaves(v)
        else:
            yield e

    def query(self, KeyConditionExpression, IndexName=None, Limit=None, ScanIndexForward=True, ExclusiveStartKey=None, **_):
        pkn, skn = ("GSI1PK", "GSI1SK") if IndexName else ("PK", "SK")
        checks = []
        for e in self._leaves(KeyConditionExpression):
            name, op = e["values"][0].name, e["operator"]
            val = e["values"][1] if len(e["values"]) > 1 else None
            checks.append((name, op, e["values"][1:] if op == "BETWEEN" else val))
        keys = [c[0] for c in checks]
        if len(keys) != len(set(keys)):  # the real service rejects this; the fake must too
            raise ClientError({"Error": {"Code": "ValidationException", "Message": "KeyConditionExpressions must only contain one condition per key"}}, "Query")
        rows = []
        for it in self.items.values():
            ok = True
            for name, op, val in checks:
                cur = it.get(name)
                if cur is None:
                    ok = False
                elif op == "=":
                    ok &= cur == val
                elif op == "begins_with":
                    ok &= str(cur).startswith(val)
                elif op == "<=":
                    ok &= str(cur) <= val
                elif op == ">=":
                    ok &= str(cur) >= val
                elif op == "<":
                    ok &= str(cur) < val
                elif op == "BETWEEN":
                    ok &= val[0] <= str(cur) <= val[1]
                else:
                    raise AssertionError(op)
            if ok:
                rows.append(it)
        rows.sort(key=lambda i: str(i.get(skn)), reverse=not ScanIndexForward)
        if Limit:
            rows = rows[:Limit]
        return {"Items": [dict(r) for r in rows]}
