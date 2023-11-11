import math


class DurationContext:
    """
    An object containing context around how duration-related operations should
    be performed. The context can be updated to affect the operations globally.
    """
    
    # Possible rounding intervals. Each interval is a two-tuple of the
    # interval in seconds, and the number of seconds into the next interval
    # that a duration must be before it is rounded up.
    ONE_MINUTE = (60, 30)
    FIVE_MINUTES = (300, 90)
    
    rounding_interval = FIVE_MINUTES
    
    @staticmethod
    def set_rounding_interval(interval):
        
        try:
            interval = int(interval)
        except ValueError:
            pass
        
        if interval == 1:
            DurationContext.rounding_interval = DurationContext.ONE_MINUTE
        elif interval == 5:
            DurationContext.rounding_interval = DurationContext.FIVE_MINUTES
        else:
            raise ValueError('Duration interval must be either 1 or 5.')


class SwitchingCostScale:
    """
    Helper object for containing scaling switching cost details and calculating
    estimated switching costs for given task durations.
    """
    
    def __init__(self, cost_range, duration_range):
        
        # Convert duration min/max given in minutes to seconds
        min_duration, max_duration = duration_range
        self.min_duration = min_duration * 60
        self.max_duration = max_duration * 60
        
        # Convert switching cost min/max given in minutes to seconds
        min_cost, max_cost = self._extract_costs(cost_range)
        self.min_cost = min_cost * 60
        self.max_cost = max_cost * 60
        
        if min_cost == max_cost:
            # There is no range of switching costs, only a single value. No
            # sliding scale needs to be used.
            self.cost_scale = None
            self.duration_step = None
        else:
            # Store a list of the full range of switching costs, in seconds
            self.cost_scale = [i * 60 for i in range(min_cost, max_cost + 1)]
            
            # Calculate the "duration step" - the number of seconds of a duration
            # between each switching cost in the above scale. E.g. there may be
            # 5 minutes (300 seconds) worth of duration between each switching cost
            # (10 minutes of duration may incur a 2 minute switching cost, and 15
            # minutes of duration may incur a 3 minute switching cost, etc).
            cost_diff = max_cost - min_cost
            duration_diff = max_duration - min_duration
            self.duration_step = math.ceil(duration_diff / cost_diff) * 60
    
    def _extract_costs(self, cost_range):
        
        invalid_msg = (
            'Invalid config: Switching cost must be a range of minutes,'
            ' e.g. 1-15, 5-30, etc.'
        )
        
        try:
            min_cost, max_cost = cost_range.split('-')
            min_cost, max_cost = int(min_cost), int(max_cost)
        except ValueError:
            raise ValueError(invalid_msg)
        
        if min_cost < 0 or min_cost > max_cost:
            raise ValueError(invalid_msg)
        
        # Find the maximum span of a switching cost range that can be
        # configured for the given duration range. The span of switching
        # costs must be under half that of the duration. E.g. a duration
        # range of 0-60 minutes supports a maximum switching cost span of
        # 30 minutes. That could mean a range of 0-30 minutes, 15-45
        # minutes, etc. Shorter spans are valid as well, this only
        # gives the maximum possible.
        max_range = int((self.max_duration - self.min_duration) / 60 / 2)
        
        if max_cost - min_cost > max_range:
            raise ValueError(
                'Invalid config: Switching cost must be a range spanning no'
                f' more than {max_range} minutes.'
            )
        
        return min_cost, max_cost
    
    def for_duration(self, duration):
        """
        Return the switching cost for the given duration, in seconds.
        """
        
        if not self.cost_scale:
            # There is only a single switching cost, so use that
            return self.min_cost
        
        # Calculate the appropriate switching cost based on a sliding scale
        # relative to the given duration. If the duration exceeds the bounds
        # of the scale, use the min/max switching cost as appropriate.
        if duration <= self.min_duration:
            return self.min_cost
        elif duration >= self.max_duration:
            return self.max_cost
        else:
            index = duration // self.duration_step
            return self.cost_scale[index]


def parse_duration_timestamp(timestamp_str):
    """
    Return the number of seconds represented by the given duration timestamp
    string. The string should be in the format "H:M:S", representing the hours,
    minutes, and seconds comprising the duration.
    
    :param timestamp_str: The duration timestamp string.
    :return: The number of seconds represented by the duration timestamp string.
    """
    
    # Extract hours, minutes, and seconds from the string and cast as integers
    hours, minutes, seconds = map(int, timestamp_str.split(':'))
    
    # Convert the duration into seconds
    return hours * 3600 + minutes * 60 + seconds


def parse_duration_input(input_str):
    """
    Return the number of seconds represented by the given duration input string.
    The string should be in the format "Xh Ym", representing the hours and
    minutes comprising the duration.
    
    :param input_str: The duration input string.
    :return: The number of seconds represented by the duration input string.
    """
    
    # Extract hours and minutes from the string and cast as integers
    parts = input_str.split()
    hours, minutes = 0, 0
    for part in parts:
        if part.endswith('h'):
            hours = int(part[:-1])
        elif part.endswith('m'):
            minutes += int(part[:-1])
        else:
            raise ValueError('Invalid duration string format. Only hours and minutes are supported.')
    
    # Convert the duration into seconds
    return hours * 3600 + minutes * 60


def round_duration(total_seconds):
    """
    Round the given number of seconds as dictated by ``DurationContext`` and
    return the new value in seconds. Values will never be rounded down to 0,
    and values that are already 0 will never be rounded up.
    
    :param total_seconds: The duration to round, in seconds.
    :return: The rounded value, in seconds.
    """
    
    interval, rounding_point = DurationContext.rounding_interval
    
    # If a zero duration, report it as such. But for other durations less
    # than the interval, report the interval as a minimum instead.
    if not total_seconds:
        return 0
    elif total_seconds < interval:
        return interval
    
    # Round to the most appropriate interval
    base, remainder = divmod(total_seconds, interval)
    
    duration = interval * base
    
    # Round up if the remainder is at or over the rounding point
    if remainder >= rounding_point:
        duration += interval
    
    return duration


def format_duration(total_seconds):
    """
    Return a human-readable string describing the given duration in hours,
    minutes, and seconds. E.g. 1h 30m.
    
    :param total_seconds: The duration, in seconds.
    :return: The string representation of the duration.
    """
    
    # Calculate hours, minutes, and seconds
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    # Create the formatted duration string
    parts = []
    if hours > 0:
        parts.append(f'{hours}h')
    if minutes > 0:
        parts.append(f'{minutes}m')
    if seconds > 0:
        parts.append(f'{seconds}s')
    
    if not parts:
        # The most common unit is minutes, so for durations of zero, report
        # it as 0 minutes.
        return '0m'
    
    return ' '.join(parts)
