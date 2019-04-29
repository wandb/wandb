"""
Base classes to be inherited from for Search and EarlyTerminate algorithms
"""


class Search():
    def _load_early_terminate_from_config(self, sweep_config):
        if not 'early_terminate' in sweep_config:
            return None

        et_config = sweep_config['early_terminate']
        if not 'type' in et_config:
            raise ValueError("Didn't specify early terminate type")

        if et_config['type'] == 'envelope':
            kw_args = {}
            if 'fraction' in et_config:
                kw_args['fraction'] = et_config['fraction']
            if 'min_runs' in et_config:
                kw_args['min_runs'] = et_config['min_runs']
            if 'start_iter' in et_config:
                kw_args['start_iter'] = et_config['start_iter']

            return envelope_stopping.EnvelopeEarlyTerminate(**kw_args)
        elif et_config['type'] == 'hyperband':
            # one way of defining hyperband, with max_iter, s and possibly eta
            if 'max_iter' in et_config:
                max_iter = et_config['max_iter']
                eta = 3
                if 'eta' in et_config:
                    eta = et_config['eta']

                s = 0
                if 's' in et_config:
                    s = et_config['s']
                else:
                    raise "Must define s for hyperband algorithm if max_iter is defined"

                return hyperband_stopping.HyperbandEarlyTerminate.init_from_max_iter(max_iter, eta, s)
            # another way of defining hyperband with min_iter and possibly eta
            if 'min_iter' in et_config:
                min_iter = et_config['min_iter']
                eta = 3
                if 'eta' in et_config:
                    eta = et_config['eta']
                return hyperband_stopping.HyperbandEarlyTerminate.init_from_min_iter(min_iter, eta)


        else:
            raise 'unsupported early termination type %s'.format(
                et_config['type'])

    def _metric_from_run(self, sweep_config, run):
        metric_name = sweep_config['metric']['name']

        maximize = False
        if 'goal' in sweep_config['metric']:
            if sweep_config['metric']['goal'] == 'maximize':
                maximize = True

        if metric_name in run.summaryMetrics:
            metric = run.summaryMetrics[metric_name]
        else:
            # maybe should do something other than erroring
            raise ValueError(
                "Couldn't find summary metric {}".format(metric_name))

        if maximize:
            metric = -metric

        return metric

    def next_run(self, sweep):
        """Called each time an agent requests new work.
        Args:
            sweep: <defined above>
        Returns:
            None if all work complete for this sweep. A dictionary of configuration
            parameters for the next run.
        """
        raise NotImplementedError

    def stop_runs(self, sweep):
        """Choose which runs to early stop if applicable.
        This will be called from a cron job every 30 seconds.
        Args:
            sweep: <defined above>
        Returns:
            Return the list of run names to early stop, empty list if there are no
            runs to stop now.
        """
        early_terminate = self._load_early_terminate_from_config(
            sweep['config'])
        if early_terminate is None:
            return []
        else:
            return early_terminate.stop_runs(sweep['config'], sweep['runs'])


class EarlyTerminate():
    def _load_metric_name_and_goal(self, sweep_config):
        if not 'metric' in sweep_config:
            raise ValueError("Key 'metric' required for early termination")

        self.metric_name = sweep_config['metric']['name']

        self.maximize = False
        if 'goal' in sweep_config['metric']:
            if sweep_config['metric']['goal'] == 'maximize':
                self.maximize = True

    def _load_run_metric_history(self, run):
        metric_history = []
        for line in run.history:
            if self.metric_name in line:
                m = line[self.metric_name]
                metric_history.append(m)

        if self.maximize:
            metric_history = [-m for m in metric_history]

        return metric_history

    def stop_runs(sweep_config, runs):
        return []
