"""
    Author: Preston Taylor
    https://github.com/PrestonTaylor
"""

import os

if (3, 9) > tuple(map(int, os.sys.version_info[:2])):
    raise Exception("Python version must be 3.9 or greater")

import logging
import yaml
import time
import traceback
from jsonpath_ng.ext import parse
from dataclasses import field, dataclass
from importlib import import_module
from typing import Union, Any
from re import search as regex_search, compile as regex_compile
from flask import Flask, Response, request


app = Flask(__name__)
if os.environ.get("BASIC_AUTH_USERNAME") and os.environ.get("BASIC_AUTH_PASSWORD"):
    app.config["BASIC_AUTH_FORCE"] = True
    app.config["BASIC_AUTH_USERNAME"] = os.environ.get("BASIC_AUTH_USERNAME")
    app.config["BASIC_AUTH_PASSWORD"] = os.environ.get("BASIC_AUTH_PASSWORD")
log = logging.getLogger("json_exporter")
log.setLevel(logging.INFO)
log.addHandler(logging.StreamHandler())


@dataclass
class MetricDefinition:
    """
    json_path: jsonpath to the metric.
    help_text: Help text for prometheus # HELP comment.
    keep_labels: List of labels to keep.
    parent_labels: Dict of parent keys to get for labels, see get_parent_key_labels.
    drop_labels: List of strings, labels to drop.
    sibling_labels_str: default True (get all) bool, str or list of sibling labels to keep of string value.
        String must be a regex. List is a list of strings for exact match.
    sibling_labels_num: default False (get none) bool, str or list of sibling labels to keep of number value.
        String must be a regex. List is a list of strings for exact match.
    left_labels: default False (get none) bool, str or list of left (ancestor) labels to keep. String must be a regex.
        List is a list of strings for exact match.
    meta_labels: Include exporter metadata labels.
    prom_type: The prometheus metric type ["counter", "gauge", "histogram", "summary", "untyped"].
    static_labels: Static labels to apply.
    prefix_name: Prefix to apply to the metric name.
    convert_string_values: default False Attempt to convert string values to int or float.
    drop_label_values: Drop labels with these values, list of exact match values.
    drop_zero_values: default False Drop metrics with a value of 0.
    """

    json_path: str
    help_text: str = None
    keep_labels: list = field(default_factory=list)
    parent_labels: dict = None
    drop_labels: list = field(default_factory=list)
    sibling_labels_str: Union[bool, str, list] = True
    sibling_labels_num: Union[bool, str, list] = False
    left_labels: Union[bool, str, list] = False
    meta_labels: bool = True
    _prom_type: str = field(init=True, default_factory=str)
    static_labels: dict = field(default_factory=dict)
    _prefix_comment: str = field(init=False)
    prefix_name: str = None
    convert_string_values: bool = False
    drop_label_values: list = field(default_factory=list)
    drop_zero_values: bool = False

    @property
    def prom_type(self):
        return self._prom_type

    @prom_type.setter
    def prom_type(self, value):
        if value not in ["counter", "gauge", "histogram", "summary", "untyped"]:
            raise ValueError(f"Invalid prometheus type {value}")
        self._prom_type = value

    @property
    def prefix_comment(self):
        if self.help_text:
            yield f"# HELP {self.help_text}\n"
        if self.prom_type:
            yield f"# TYPE {self.prom_type}\n"

    @prefix_comment.setter
    def prefix_comment(self, value):
        self._prefix_comment = value


@dataclass
class ScrapeConfig:
    scraper_settings: dict[str, Any] = field(default_factory=dict)
    scraper_type: str = "http"
    fix_nested_data: list = field(default_factory=list)
    metrics: dict[str, MetricDefinition] = field(default_factory=dict)


@dataclass
class ModuleConfig:
    scrapes: dict[str, ScrapeConfig] = field(default_factory=dict)


@dataclass
class Config:
    modules: dict[str, ModuleConfig] = field(default_factory=dict)


class JsonExporter:
    def __init__(self, configfile: str = None):
        self.loadedconfig: Config = None
        self.app = Flask(__name__)
        self.app.add_url_rule("/json", "metric_stream", self.metric_stream)
        self.app.add_url_rule("/metrics", "metric_stream", self.metric_stream)
        try:
            if not os.path.isabs(configfile):
                path = os.path.join(os.path.dirname(os.path.abspath(__file__)), configfile)
            else:
                path = configfile
            with open(path, "r") as f:
                textconfig = yaml.safe_load(f)
            self.loadedconfig = Config()
            for module, moduleconfig in textconfig["modules"].items():
                try:
                    self.loadedconfig.modules[module] = ModuleConfig(
                        **{k: v for k, v in moduleconfig.items() if k != "scrape_configs"}
                    )
                except Exception as e:
                    log.error(f"Invalid config at {module}")
                    log.error(e)
                    raise e
                for scrape, scrapeconfig in moduleconfig["scrape_configs"].items():
                    try:
                        self.loadedconfig.modules[module].scrapes[scrape] = ScrapeConfig(
                            **{k: v for k, v in scrapeconfig.items() if k != "metrics"}
                        )
                        # validate scraper settings
                        # load scraper class and dataclass for Settings
                        scraperModule = import_module(
                            f"Scraper.{self.loadedconfig.modules[module].scrapes[scrape].scraper_type}"
                        )
                        Settings = getattr(scraperModule, "Settings")
                        if "scraper_settings" in scrapeconfig:
                            self.loadedconfig.modules[module].scrapes[scrape].scraper_settings = Settings(
                                **scrapeconfig["scraper_settings"]
                            )
                        else:
                            self.loadedconfig.modules[module].scrapes[scrape].scraper_settings = Settings()
                        self.loadedconfig.modules[module].scrapes[scrape].Scraper_class = getattr(
                            scraperModule, self.loadedconfig.modules[module].scrapes[scrape].scraper_type
                        ).fget()

                    except Exception as e:
                        log.error(f"Invalid config at {module}/{scrape}")
                        log.error(e)
                        raise e
                    for key, value in scrapeconfig["metrics"].items():
                        try:
                            self.loadedconfig.modules[module].scrapes[scrape].metrics[key] = MetricDefinition(**value)
                        except Exception as e:
                            log.error(f"Invalid config at {module}/{scrape}/{key}")
                            log.error(e)
                            raise e
                        try:
                            _ = parse(value["json_path"])
                        except Exception as e:
                            log.error(f"invalid jsonpath at {module}/{scrape}/{key}")
                            raise e
                        try:
                            if isinstance(value.get("sibling_labels_str"), str):
                                regex_compile(value["sibling_labels_str"])
                            if isinstance(value.get("sibling_labels_num"), str):
                                regex_compile(value["sibling_labels_num"])
                            if isinstance(value.get("left_labels"), str):
                                regex_compile(value["left_labels"])
                        except Exception as e:
                            log.error(f"invalid regex at {module}/{scrape}/{key}")
                            raise e

        except FileNotFoundError as e:
            log.error("json_export: config file not found")
            log.error(e)
            raise e
        except Exception as e:
            log.error("json_export: config file load error")
            log.error(e)
            raise e
        log.info("Config loaded")

    def get_metric_value(self, metric, metricdef):
        """
        Returns the value of a metric based on the metric definition.
        Attempts to convert string values to int or float if convert_string_values is set.
        """
        if isinstance(metric.value, bool):
            return int(metric.value)
        if metricdef.convert_string_values and isinstance(metric.value, str):
            try:
                if "." in metric.value:
                    return float(metric.value)
                else:
                    return int(metric.value)
            except ValueError:
                return None
        if not isinstance(metric.value, int) and not isinstance(metric.value, float):
            return None
        return metric.value

    def get_labels(self, metric, modulename: str, scrapename: str, metricname):
        """
        Returns labels for a metric based on the metric definition
        """
        metricdef: MetricDefinition = self.loadedconfig.modules[modulename].scrapes[scrapename].metrics[metricname]
        labels = {}
        labels.update(self.get_left_labels(metric, metricdef.left_labels))
        if metricdef.sibling_labels_str or metricdef.sibling_labels_num:
            labels.update(self.get_sibling_labels(metric, metricdef))
        if metricdef.parent_labels:
            labels.update(self.get_parent_key_labels(metric, metricdef))
        if metricdef.meta_labels:
            labels.update(
                {
                    "exporter_module": modulename,
                    "exporter_scrape": scrapename,
                    "exporter_metric": metricname,
                }
            )
        if metricdef.static_labels:
            labels.update(metricdef.static_labels)
        if metricdef.keep_labels:
            labels = {k: v for k, v in labels.items() if k in metricdef.keep_labels}
        if metricdef.drop_labels:
            labels = {k: v for k, v in labels.items() if k not in metricdef.drop_labels}
        if metricdef.drop_label_values:
            labels = {k: v for k, v in labels.items() if v not in metricdef.drop_label_values}
        return labels

    def get_sibling_labels(self, metric, metricdef: MetricDefinition):
        """
        Retrieves k,v pairs from context tree at the same level as the metric to use as labels.
        By default, all strings are assumed to be useful labels, numbers are ignored.
        """
        labels = {}
        for k, v in metric.context.value.items():
            if k != metric.path.fields[0]:
                if metricdef.sibling_labels_str and isinstance(v, (str, bool)) and v != "":
                    if isinstance(metricdef.sibling_labels_str, bool):
                        labels[k] = v
                    elif isinstance(metricdef.sibling_labels_str, list) and k in metricdef.sibling_labels_str:
                        labels[k] = v
                    elif isinstance(metricdef.sibling_labels_str, str) and k == metricdef.sibling_labels_str:
                        if regex_search(metricdef.sibling_labels_str, k):
                            labels[k] = v
                if metricdef.sibling_labels_num and (isinstance(v, int) or isinstance(v, float)) and v != "":
                    if isinstance(metricdef.sibling_labels_num, bool):
                        labels[k] = v
                    elif isinstance(metricdef.sibling_labels_num, list) and k in metricdef.sibling_labels_num:
                        labels[k] = v
                    elif isinstance(metricdef.sibling_labels_num, str) and k == metricdef.sibling_labels_num:
                        if regex_search(metricdef.sibling_labels_num, k):
                            labels[k] = v
        return labels

    def get_parent_key_labels(self, metric, metricdef: MetricDefinition):
        """
        retrieves parent *keys* from the context tree to use as labels.
        Format { <labelname>: <steps up the context tree> }
        example:
        parent_labels: { "mylabel": 1 }
        json: { "foo": { "barstat": 1 } }
        result: barstat{ "mylabel"="foo" } 1
        """
        labels = {}
        for k, v in metricdef.parent_labels.items():
            try:
                # v is steps up the context tree
                c = metric
                for _ in range(v):
                    c = c.context
                labels[k] = c.path.fields[0]
            except Exception as e:
                log.warning(f"Could not find parent label {k} for metric {metric.path.fields[0]}")
                log.warning(e)
        return labels

    def get_left_labels(
        self,
        metric,
        left_labels: Union[bool, list, str],
    ):
        labels = {}
        if not left_labels:
            return labels
        # context.context to avoid immediate siblings
        c = metric.context.context
        while True:
            if isinstance(c.value, list):
                # lists are usually not interesting for labels
                c = c.context
                continue
            for k, v in c.value.items():
                if isinstance(v, int) or isinstance(v, float) or isinstance(v, str) and v != "":
                    if isinstance(left_labels, bool) and left_labels:
                        labels[k] = v
                    elif isinstance(left_labels, list) and k in left_labels:
                        labels[k] = v
                    elif isinstance(left_labels, str) and k == left_labels:
                        if regex_search(left_labels, k):
                            labels[k] = v
            if getattr(c, "context", None):
                c = c.context
            else:
                break
        return labels

    def fix_nested_data(self, data, jsonpaths):
        """
        jsonpath: $..[value]
        Flattens nested data. Useful when json looks like:
        {
            "foos": {
                "foo_stat": {
                    "value": 1
                    "max": 10
                    "min": 1
                    "5minavg": 3
                    "15minavg": 4
                }
                "foo_stat_info": "bar"
            }
        }
        returns:
        {
            "foos": {
                "foo_stat":  1,
                "foo_stat_info": "bar"
            }
        }
        Allowing to easily gather relevant sibling objects for labels
        """
        for jsonpath in jsonpaths:
            jsonpath_expr = parse(jsonpath)
            for mtrc in jsonpath_expr.find(data):
                data = mtrc.context.full_path.update(data, mtrc.value)
        return data

    def get(self, target, module):
        """
        Main entry point for scraping
        """
        starttime = time.time()
        moduleconfig = self.loadedconfig.modules[module]
        for scrapename, scrape in moduleconfig.scrapes.items():
            result = scrape.Scraper_class(scrape.scraper_settings).get(target)
            if scrape.fix_nested_data:
                result = self.fix_nested_data(result, scrape.fix_nested_data)
            yield from self._process_scrape(result, module, scrapename)
        yield "\n# HELP json_exporter_scrape_duration_seconds Time taken to scrape the json\n"
        yield "# TYPE json_exporter_scrape_duration_seconds gauge\n"
        yield f'json_exporter_scrape_duration_seconds{{module="{module}"}} {time.time()-starttime}\n'
        log.info(f"Scraped target: {target}, with module: {module} in {time.time()-starttime} seconds")

    def _process_scrape(self, result, module, scrapename):
        scrape = self.loadedconfig.modules[module].scrapes[scrapename]
        dupecheck = set()
        for metricname, metricdef in scrape.metrics.items():
            jsonpath_expr = parse(metricdef.json_path)
            for mtrc in jsonpath_expr.find(result):
                value = self.get_metric_value(mtrc, metricdef)
                if value is None:
                    continue
                if metricdef.drop_zero_values and value == 0:
                    continue
                name = f"{metricdef.prefix_name or ''}{mtrc.path.fields[0]}"
                labels = self.get_labels(mtrc, module, scrapename, metricname)
                labelstr = ",".join([f'{k}="{v}"' for k, v in labels.items()])
                if (name, labelstr) in dupecheck:
                    log.error(f"Duplicate metric {name} {labels}")
                dupecheck.add((name, labelstr))
                if metricdef.help_text or metricdef.prom_type:
                    yield from metricdef.prefix_comment
                yield f"{name}{{{labelstr}}} {value}\n"

    def metric_stream(self):
        """
        Flask endpoint
        """
        target = request.args.get("target") or request.args.get("host") or request.args.get("instance")
        module = request.args.get("module")
        if not target:
            return Response("Missing host parameter", status=400)
        if not module:
            return Response("Missing module parameter", status=400)
        try:
            return Response(self.get(target, module), mimetype="text/plain")
        except Exception as e:
            log.error(e)
            log.error(traceback.format_exc())
            return Response("Internal server error", status=500)


if "JSON_EXPORTER_CONFIG" in os.environ:
    config = os.environ["JSON_EXPORTER_CONFIG"]
else:
    config = "config.yml"

exporter = JsonExporter(config)


# gunicorn entry
def application(environ, start_response):
    return exporter.app(environ, start_response)
