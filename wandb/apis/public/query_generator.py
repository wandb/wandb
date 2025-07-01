class QueryGenerator:
    """QueryGenerator is a helper object to write filters for runs."""

    INDIVIDUAL_OP_TO_MONGO = {
        "!=": "$ne",
        ">": "$gt",
        ">=": "$gte",
        "<": "$lt",
        "<=": "$lte",
        "IN": "$in",
        "NIN": "$nin",
        "REGEX": "$regex",
    }
    MONGO_TO_INDIVIDUAL_OP = {v: k for k, v in INDIVIDUAL_OP_TO_MONGO.items()}

    GROUP_OP_TO_MONGO = {"AND": "$and", "OR": "$or"}
    MONGO_TO_GROUP_OP = {v: k for k, v in GROUP_OP_TO_MONGO.items()}

    def __init__(self):
        pass

    @classmethod
    def format_order_key(cls, key: str):
        if key.startswith(("+", "-")):
            direction = key[0]
            key = key[1:]
        else:
            direction = "-"
        parts = key.split(".")
        if len(parts) == 1:
            # Assume the user meant summary_metrics if not a run column
            if parts[0] not in ["createdAt", "updatedAt", "name", "sweep"]:
                return direction + "summary_metrics." + parts[0]
        # Assume summary metrics if prefix isn't known
        elif parts[0] not in ["config", "summary_metrics", "tags"]:
            return direction + ".".join(["summary_metrics"] + parts)
        else:
            return direction + ".".join(parts)

    def _is_group(self, op):
        return op.get("filters") is not None

    def _is_individual(self, op):
        return op.get("key") is not None

    def _to_mongo_op_value(self, op, value):
        if op == "=":
            return value
        else:
            return {self.INDIVIDUAL_OP_TO_MONGO[op]: value}

    def key_to_server_path(self, key):
        if key["section"] == "config":
            return "config." + key["name"]
        elif key["section"] == "summary":
            return "summary_metrics." + key["name"]
        elif key["section"] == "keys_info":
            return "keys_info.keys." + key["name"]
        elif key["section"] == "run":
            return key["name"]
        elif key["section"] == "tags":
            return "tags." + key["name"]
        raise ValueError("Invalid key: {}".format(key))

    def server_path_to_key(self, path):
        if path.startswith("config."):
            return {"section": "config", "name": path.split("config.", 1)[1]}
        elif path.startswith("summary_metrics."):
            return {"section": "summary", "name": path.split("summary_metrics.", 1)[1]}
        elif path.startswith("keys_info.keys."):
            return {"section": "keys_info", "name": path.split("keys_info.keys.", 1)[1]}
        elif path.startswith("tags."):
            return {"section": "tags", "name": path.split("tags.", 1)[1]}
        else:
            return {"section": "run", "name": path}

    def keys_to_order(self, keys):
        orders = []
        for key in keys["keys"]:
            order = self.key_to_server_path(key["key"])
            if key.get("ascending"):
                order = "+" + order
            else:
                order = "-" + order
            orders.append(order)
        # return ",".join(orders)
        return orders

    def order_to_keys(self, order):
        keys = []
        for k in order:  # orderstr.split(","):
            name = k[1:]
            if k[0] == "+":
                ascending = True
            elif k[0] == "-":
                ascending = False
            else:
                raise Exception("you must sort by ascending(+) or descending(-)")

            key = {"key": {"section": "run", "name": name}, "ascending": ascending}
            keys.append(key)

        return {"keys": keys}

    def _to_mongo_individual(self, filter):
        if filter["key"]["name"] == "":
            return None

        if filter.get("value") is None and filter["op"] != "=" and filter["op"] != "!=":
            return None

        if filter.get("disabled") is not None and filter["disabled"]:
            return None

        if filter["key"]["section"] == "tags":
            if filter["op"] == "IN":
                return {"tags": {"$in": filter["value"]}}
            if filter["value"] is False:
                return {
                    "$or": [{"tags": None}, {"tags": {"$ne": filter["key"]["name"]}}]
                }
            else:
                return {"tags": filter["key"]["name"]}
        path = self.key_to_server_path(filter["key"])
        if path is None:
            return path
        return {path: self._to_mongo_op_value(filter["op"], filter["value"])}

    def filter_to_mongo(self, filter):
        if self._is_individual(filter):
            return self._to_mongo_individual(filter)
        elif self._is_group(filter):
            return {
                self.GROUP_OP_TO_MONGO[filter["op"]]: [
                    self.filter_to_mongo(f) for f in filter["filters"]
                ]
            }

    def mongo_to_filter(self, filter):
        # Returns {"op": "OR", "filters": [{"op": "AND", "filters": []}]}
        if filter is None:
            return None  # this covers the case where self.filter_to_mongo returns None.

        group_op = None
        for key in filter.keys():
            # if self.MONGO_TO_GROUP_OP[key]:
            if key in self.MONGO_TO_GROUP_OP:
                group_op = key
                break
        if group_op is not None:
            return {
                "op": self.MONGO_TO_GROUP_OP[group_op],
                "filters": [self.mongo_to_filter(f) for f in filter[group_op]],
            }
        else:
            for k, v in filter.items():
                if isinstance(v, dict):
                    # TODO: do we always have one key in this case?
                    op = next(iter(v.keys()))
                    return {
                        "key": self.server_path_to_key(k),
                        "op": self.MONGO_TO_INDIVIDUAL_OP[op],
                        "value": v[op],
                    }
                else:
                    return {"key": self.server_path_to_key(k), "op": "=", "value": v}
