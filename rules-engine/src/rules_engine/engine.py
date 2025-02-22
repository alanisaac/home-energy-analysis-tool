import statistics as sts
from enum import Enum
from typing import List, Tuple

import numpy as np


def hdd(avg_temp: float, balance_point: float) -> float:
    """Calculate the heating degree days on a given day for a given home.

    Arguments:
    avg_temp -- average outdoor temperature on a given day
    balance_point -- outdoor temperature above which no heating is required in
    a given home
    """
    diff = balance_point - avg_temp

    if diff < 0:
        return 0
    else:
        return diff


def period_hdd(avg_temps: List[float], balance_point: float) -> float:
    """Sum up total heating degree days in a given time period for a given home.

    Arguments:
    avg_temps -- list of daily average outdoor temperatures (F) for the period
    balance_point -- outdoor temperature (F) above which no heating is required
    in a given home
    """
    return sum([hdd(temp, balance_point) for temp in avg_temps])


def average_indoor_temp(
    tstat_set: float, tstat_setback: float, setback_daily_hrs: float
) -> float:
    """Calculates the average indoor temperature.

    Arguments:
    tstat_set -- the temp in F at which the home is normally set
    tstat_setback -- temp in F at which the home is set during off hours
    setback_daily_hrs -- average # of hours per day the home is at setback temp
    """
    # again, not sure if we should check for valid values here or whether we can
    # assume those kinds of checks will be handled at the point of user entry
    return (
        (24 - setback_daily_hrs) * tstat_set + setback_daily_hrs * tstat_setback
    ) / 24


def average_heat_load(
    design_set_point: float, avg_indoor_temp: float, balance_point: float, design_temp: float, ua: float
) -> float:
    """Calculate the average heat load. 

    Arguments:
    design_set_point -- a standard internal temperature / thermostat set point - different from the preferred set point of an individual homeowner
    avg_indoor_temp -- average indoor temperature on a given day
    balance_point -- outdoor temperature (F) above which no heating is required
    design_temp -- an outside temperature that represents one of the coldest days of the year for the given location of a home
    ua -- the heat transfer coefficient 
    """
    return (
        design_set_point - (avg_indoor_temp - balance_point) - design_temp
    ) * ua


def max_heat_load(
    design_set_point: float, design_temp: float, ua: float
) -> float:
    """Calculate the max heat load. 

    Arguments:
    design_set_point -- a standard internal temperature / thermostat set point - different from the preferred set point of an individual homeowner
    design_temp -- an outside temperature that represents one of the coldest days of the year for the given location of a home
    ua -- the heat transfer coefficient 
    """
    return (
        design_set_point - design_temp
    ) * ua


class FuelType(Enum):
    """Enum for fuel types. Values are BTU per usage"""

    GAS = 100000
    OIL = 139600
    PROPANE = 91333


class Home:
    """Defines attributes and methods for calculating home heat metrics"""

    def __init__(
        self,
        fuel_type: FuelType,
        heat_sys_efficiency: float,
        initial_balance_point: float = 60,
        thermostat_set_point: float = 68,
    ):
        self.fuel_type = fuel_type
        self.heat_sys_efficiency = heat_sys_efficiency
        self.balance_point = initial_balance_point
        self.thermostat_set_point = thermostat_set_point

    def initialize_billing_periods(
        self,
        temps: List[List[float]],
        usages: List[float],
        avg_non_heating_usage: float = 0,
    ) -> None:
        """Eventually, this method should categorize the billing periods by
        season and calculate avg_non_heating_usage based on that. For now, we
        just pass in winter-only heating periods and manually define non-heating
        """
        # assume for now that temps and usages have the same number of elements
        self.bills = []
        self.avg_non_heating_usage = avg_non_heating_usage

        for i in range(len(usages)):
            self.bills.append(BillingPeriod(temps[i], usages[i], self))

    def calculate_balance_point_and_ua(
        self,
        initial_balance_point_sensitivity: float = 2,
        stdev_pct_max: float = 0.10,
        max_stdev_pct_diff: float = 0.01,
        next_balance_point_sensitivity: float = 0.5,
    ) -> None:
        """Calculates the estimated balance point and UA coefficient for the home,
        removing UA outliers based on a normalized standard deviation threshold.
        """
        self.uas = [bp.ua for bp in self.bills]
        self.avg_ua = sts.mean(self.uas)
        self.stdev_pct = sts.pstdev(self.uas) / self.avg_ua
        self.refine_balance_point(initial_balance_point_sensitivity)

        while self.stdev_pct > stdev_pct_max:
            biggest_outlier_idx = np.argmax(
                [abs(bill.ua - self.avg_ua) for bill in self.bills]
            )
            outlier = self.bills.pop(biggest_outlier_idx)  # removes the biggest outlier
            uas_i = [bp.ua for bp in self.bills]
            avg_ua_i = sts.mean(uas_i)
            stdev_pct_i = sts.pstdev(uas_i) / avg_ua_i
            if (
                self.stdev_pct - stdev_pct_i < max_stdev_pct_diff
            ):  # if it's a small enough change
                self.bills.append(
                    outlier
                )  # then it's not worth removing it, and we exit
                break  # may want some kind of warning to be raised as well
            else:
                self.uas, self.avg_ua, self.stdev_pct = uas_i, avg_ua_i, stdev_pct_i

            self.refine_balance_point(next_balance_point_sensitivity)


    def calculate_balance_point_and_ua_customizable(
        self, 
        bps_to_remove: List, # List[BillingPeriod]
        balance_point_sensitivity: float = 2, 
    ) -> None:
        """Calculates the estimated balance point and UA coefficient for the home based on user input 

        Arguments:
        bps_to_remove: a list of Billing Periods that user wishes to remove from calculation
        """

        # 1. user enters a list of BillingPeriods and presses calculate
        # 2. function calculates bp and UA, display a graph of UA values including outliers
        # 3. user can de-select individual BillingPeriods (one with UA outliers or not) 
        #    thru a checkbox, removing them from self.bills. user presses 'calculate'
        # 4. go back to step 2

        customized_bills = [bp for bp in self.bills if bp not in bps_to_remove]
        self.uas = [bp.ua for bp in customized_bills]
        self.avg_ua = sts.mean(self.uas)
        self.stdev_pct = sts.pstdev(self.uas) / self.avg_ua

        self.bills = customized_bills # I believe self.bills should be modified here so self.refine_balance_point() generates a different bp
        self.refine_balance_point(balance_point_sensitivity)
        

    def refine_balance_point(self, balance_point_sensitivity: float) -> None:
        """Tries different balance points plus or minus a given number of degrees,
        choosing whichever one minimizes the standard deviation of the UAs.
        """
        directions_to_check = [1, -1]

        while directions_to_check:
            bp_i = (
                self.balance_point + directions_to_check[0] * balance_point_sensitivity
            )

            if bp_i > self.thermostat_set_point:
                break  # may want to raise some kind of warning as well

            period_hdds_i = [period_hdd(bill.avg_temps, bp_i) for bill in self.bills]
            uas_i = [
                bill.partial_ua / period_hdds_i[n] for n, bill in enumerate(self.bills)
            ]
            avg_ua_i = sts.mean(uas_i)
            stdev_pct_i = sts.pstdev(uas_i) / avg_ua_i

            if stdev_pct_i < self.stdev_pct:
                self.balance_point, self.avg_ua, self.stdev_pct = (
                    bp_i,
                    avg_ua_i,
                    stdev_pct_i,
                )

                for n, bill in enumerate(self.bills):
                    bill.total_hdd = period_hdds_i[n]
                    bill.ua = uas_i[n]

                if len(directions_to_check) == 2:
                    directions_to_check.pop(-1)
            else:
                directions_to_check.pop(0)


class BillingPeriod:
    def __init__(
        self,
        avg_temps: List[float],
        usage: float,
        home: Home,
    ):
        self.avg_temps = avg_temps
        self.usage = usage
        self.home = home
        self.days = len(self.avg_temps)
        self.avg_heating_usage = (
            self.usage / self.days
        ) - self.home.avg_non_heating_usage
        self.total_hdd = period_hdd(self.avg_temps, self.home.balance_point)
        self.partial_ua = self.calculate_partial_ua()
        self.ua = self.partial_ua / self.total_hdd

    def calculate_partial_ua(self):
        """The portion of UA that is not dependent on the balance point"""
        return (
            self.days
            * self.avg_heating_usage
            * self.home.fuel_type.value
            * self.home.heat_sys_efficiency
            / 24
        )