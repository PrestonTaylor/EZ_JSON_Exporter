# Ez JSON Exporter
This is a Prometheus JSON exporter that scrapes an endpoint and exports it in Prometheus format on demand. It is designed to  be easily configurable while being more flexible than the official Prometheus JSON exporter which unfortunately has an extremely limited implementation of JSONPath. Performance will be worse but I would gladly trade CPU time for my time. The goal of this is to be able to export arbitrary numbers of metrics at arbitrary nested levels and locations and likely appropriate labels with only a single line or 2 of config. 
    
Because lots of defaults are set for you and some assumptions are made about what labels you might want unless you specify, it's possible to get duplicate series. Check logs and output.

## Usage

1. **Configuration**:
   - Edit the `config.yml` file to define the modules and scrape configurations. Each module can have multiple scrape configurations, and each scrape configuration can have multiple metrics defined using JSONPath expressions.

2. **Environment Variables**:
   - Set the `JSON_EXPORTER_CONFIG` environment variable to the path of your configuration file if it is not named `config.yml` or located in the same directory as the script.
   - Optionally, set `BASIC_AUTH_USERNAME` and `BASIC_AUTH_PASSWORD` environment variables for basic authentication.

3. **Running the Exporter**:
   - Run the exporter using a WSGI server like Gunicorn:
     ```sh
     python3.9 -m gunicorn -b 0.0.0.0:9469 'json-exporter:application' -w 1 -k gevent
     ```
     gevent worker recommended if this is acting as a proxy to make another network request. Other worker types or default will function.

4. **Scraping Metrics**:
   - Access the metrics by making a GET request to the `/metrics` endpoint with the required query parameters:
     ```sh
     curl "http://localhost:9469/metrics?target=<TARGET>&module=<MODULE>"
     ```

   - Add a scrape job to your Prometheus configuration to scrape the JSON Exporter endpoint:
     ```yaml
     scrape_configs:
        - job_name: jsonexporter
            scheme: http
            basic_auth:
                username: user
                password: password
            metrics_path: /metrics
            params:
                module:
                - mymodule
            relabel_configs:
                - source_labels:
                    - __address__
                    target_label: __param_target
                - source_labels:
                    - __param_target
                    target_label: instance
                - target_label: __address__
                    replacement: myexporterfqdnorip:9469
            static_configs:
            - targets:
                - foo-01.bar.com
     ```
6. **JSON Exporter Configuration**:
   - Refer to https://github.com/h2non/jsonpath-ng for JSONPath implementation.
    ### Example Config
    ```yaml
        ---
        modules:
        # Define a module named 'example_module'
            example_module:
                scrape_configs:
                # Define a scrape configuration named 'example_scrape'
                    example_scrape:
                        # Optional: Fix nested (un-nest) data using JSONPath expressions, moves this element up the tree, replacing its' parent.
                        fix_nested_data: ["$..[nested][data]..[value]"]
                        scraper_type: http # See Scraper/ dir
                        # Scraper settings specific to the scraper type
                        scraper_settings: # Unique to the scraper chosen, see class.
                            scheme: "http"  # Scheme to use (http or https)
                            insecure: true  # Allow insecure connections (e.g., self-signed certificates)
                            username: example_user  # Username for basic authentication
                            password: example_password  # Password for basic authentication
                            path: "/api/metrics"  # Path to the metrics endpoint
                            # Define the metrics to scrape
                        metrics:
                        # Define a metric named 'example_metric'
                            example_metric: # *** json_path is the only required option here ***
                                json_path: "$[*]..*['metric_value']"  # See https://github.com/h2non/jsonpath-ng
                                help_text: "Example metric help text"  # Help text for Prometheus # HELP comment
                                keep_labels: ["label1", "label2"]
                                drop_labels: ["unwanted_label"]
                                sibling_labels_str: True  # JSON siblings with str type to make a new label with (True=All)
                                sibling_labels_num: False # JSON siblings with int or float type to make a new label with (True=All)
                                left_labels: False  # Do not keep any ancestor labels
                                meta_labels: True  # Include exporter metadata labels
                                prom_type: "gauge"  # Prometheus metric type (e.g., counter, gauge, etc.)
                                static_labels: {"static_label": "value"}  # Static labels to apply
                                prefix_name: "example_"  # Prefix to apply to the metric name
                                convert_string_values: False  # Do not attempt to convert string values to int or float
                                drop_label_values: ["unwanted_value"]  # Drop labels with these values
                                drop_zero_values: False
                                ```
## TODO
Some config options may be more appropriate as jsonpaths or regex rather than string match. 
Explore config option to choose a modularized JSONPath implementation.
Other things probably.