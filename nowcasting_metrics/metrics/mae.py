""" Function to make MAE """
import logging
from typing import Optional, Union

from nowcasting_datamodel import N_GSP
from nowcasting_datamodel.models import ForecastValueLatestSQL, ForecastValueSQL, Metric
from nowcasting_datamodel.models.gsp import GSPYieldSQL, LocationSQL
from nowcasting_datamodel.models.metric import DatetimeInterval
from nowcasting_datamodel.read.read import get_location
from sqlalchemy.orm.session import Session
from sqlalchemy.sql import func

from nowcasting_metrics.metrics.utils import (
    filter_query_on_datetime_interval,
    make_forecast_sub_query,
    make_gsp_sub_query,
    make_pvlive_subquery,
)
from nowcasting_metrics.utils import save_metric_value_to_database

logger = logging.getLogger(__name__)


latest_mae = Metric(
    name="Daily Latest MAE",
    description="This metric calculates the MAE for the latest OCF forecast "
    "and compares with the PVLive values. The data is from one day",
)

mae_all_gsps = Metric(
    name="Daily Latest MAE All GSPs",
    description="This metric calculates the MAE for the latest OCF forecast "
    "and compares with the PVLive values. The data is from one day. "
    "This is for all GSPs (not the national)",
)

pvlive_mae = Metric(
    name="PVLive MAE",
    description="This metric calculates the MAE for the initial estimate by "
    "PVLive and the updated estimate. The data is from one day for each GSP.",
)


def make_pvlive_mae(
    session: Session, datetime_interval: DatetimeInterval, gsp_id: int
) -> (int, int):
    """
    Calculate MAE for the PV Live initial and updates estimate

    :param session: database sessions
    :param datetime_interval: datetime interval
    :param gsp_id: the gsp id
    :return:  1. the MAE, 2. the number of data points
    """

    sub_query_day_after = make_pvlive_subquery(
        session=session, datetime_interval=datetime_interval, gsp_id=gsp_id, regime="day-after"
    ).subquery()

    sub_query_in_day = make_pvlive_subquery(
        session=session, datetime_interval=datetime_interval, gsp_id=gsp_id, regime="in-day"
    ).subquery()

    query = session.query(
        func.avg(
            func.abs(
                sub_query_day_after.c.solar_generation_kw / 1000
                - sub_query_in_day.c.solar_generation_kw / 1000
            )
        ),
        func.count(sub_query_day_after.c.datetime_utc),
    )

    query = query.join(
        sub_query_in_day, sub_query_day_after.c.datetime_utc == sub_query_in_day.c.datetime_utc
    )
    results = query.all()

    number_of_data_points = results[0][1]
    value = results[0][0]

    logger.debug(
        f"Found PVlive MAE of {value} from {number_of_data_points} " f"data points for {gsp_id=}."
    )

    save_metric_value_to_database(
        session=session,
        value=value,
        number_of_data_points=number_of_data_points,
        datetime_interval=datetime_interval,
        metric=pvlive_mae,
        location=get_location(gsp_id=gsp_id, session=session),
    )

    return value, number_of_data_points


def make_mae_one_gsp_with_forecast_horizon(
    session: Session,
    datetime_interval: DatetimeInterval,
    gsp_id: int,
    forecast_horizon_minutes: int,
) -> (int, int):
    """
    Calculate the MAE for one GSP for a forecast horizon, and save to database

    :param session: database session
    :param datetime_interval: datetime interbal
    :param gsp_id: the gsp id
    :param forecast_horizon_minutes: the forecast horizon ie. Use results from forecast that are
        made 60 minutes before target time
    :return: 1. the MAE, 2. the number of data points
    """

    sub_query_gsp = make_gsp_sub_query(datetime_interval, gsp_id, session)
    sub_query_forecast = make_forecast_sub_query(
        datetime_interval, forecast_horizon_minutes, gsp_id, session
    )

    # make full query
    query = make_mae_query(session, model=ForecastValueSQL)

    query = query.filter(ForecastValueSQL.uuid.in_(sub_query_forecast))
    query = query.filter(GSPYieldSQL.id.in_(sub_query_gsp))
    query = query.filter(GSPYieldSQL.datetime_utc == ForecastValueSQL.target_time)
    results = query.all()

    number_of_data_points = results[0][1]
    value = results[0][0]

    logger.debug(
        f"Found MAE of {value} from {number_of_data_points} "
        f"data points for forecast horizon {forecast_horizon_minutes} for {gsp_id=}."
    )

    save_metric_value_to_database(
        session=session,
        value=value,
        number_of_data_points=number_of_data_points,
        datetime_interval=datetime_interval,
        metric=latest_mae,
        location=get_location(gsp_id=gsp_id, session=session),
        forecast_horizon_minutes=forecast_horizon_minutes,
    )

    return value, number_of_data_points


def make_mae_one_gsp(
    session: Session, datetime_interval: DatetimeInterval, gsp_id: int
) -> (int, int):
    """
    Calculate the MAE for one GSP, and save to database

    :param session: database session
    :param datetime_interval: datetime interval
    :param gsp_id: the gsp id
    :return: 1. the MAE, 2. the number of data points
    """

    logger.debug(
        f"Calculating MAE for last forecast for {gsp_id=} for "
        f"start={datetime_interval.end_datetime_utc} "
        f"and end-{datetime_interval.end_datetime_utc}"
    )

    query = make_mae_query(session)

    # filter on gsp
    query = query.filter()

    # filter on target time
    query = query.join(GSPYieldSQL.location)
    query = query.filter(LocationSQL.gsp_id == gsp_id)
    query = query.filter(ForecastValueLatestSQL.gsp_id == gsp_id)

    # join target time and yield
    query = filter_query_on_datetime_interval(datetime_interval, query)

    # filter on gsp regime
    query = query.filter(GSPYieldSQL.regime == "day-after")

    results = query.all()

    number_of_data_points = results[0][1]
    value = results[0][0]

    logger.debug(f"Found MAE of {value} from {number_of_data_points} data points.")

    save_metric_value_to_database(
        session=session,
        value=value,
        number_of_data_points=number_of_data_points,
        datetime_interval=datetime_interval,
        metric=latest_mae,
        location=get_location(gsp_id=gsp_id, session=session),
    )

    return value, number_of_data_points


def make_mae_all_gsp(session: Session, datetime_interval: DatetimeInterval) -> (int, int):
    """
    Calculate the MAE for all GSPs (not national), and save to database

    :param session: database session
    :param datetime_interval: datetime interbal
    :return: 1. the MAE, 2. the number of data points
    """

    logger.debug(
        f"Calculating MAE for last forecast for all gsps (not national) for "
        f"start={datetime_interval.end_datetime_utc} "
        f"and end-{datetime_interval.end_datetime_utc}"
    )

    query = make_mae_query(session)

    # filter on gsp
    query = query.filter()

    # filter on target time
    query = query.join(GSPYieldSQL.location)
    query = query.filter(LocationSQL.gsp_id != 0)
    query = query.filter(ForecastValueLatestSQL.gsp_id != 0)
    query = query.filter(ForecastValueLatestSQL.gsp_id == LocationSQL.gsp_id)

    # only include non nan values
    query = query.filter(GSPYieldSQL.solar_generation_kw + 1 > GSPYieldSQL.solar_generation_kw)

    # join target time and yield
    query = filter_query_on_datetime_interval(datetime_interval, query)

    # filter on gsp regime
    query = query.filter(GSPYieldSQL.regime == "day-after")

    results = query.all()

    number_of_data_points = results[0][1]
    value = results[0][0]

    logger.debug(
        f"Found MAE of {value} from {number_of_data_points} data points, "
        f"for all gsps (not national)"
    )

    save_metric_value_to_database(
        session=session,
        value=value,
        number_of_data_points=number_of_data_points,
        datetime_interval=datetime_interval,
        metric=mae_all_gsps,
        location=None,
    )

    return value, number_of_data_points


def make_mae_query(
    session, model: Union[ForecastValueSQL, ForecastValueLatestSQL] = ForecastValueLatestSQL
):
    """
    Make MAE query

    :param session: database sessions
    :param model: either ForecastValueSQL or ForecastValueLatestSQL
    :return: query
    """
    query = session.query(
        func.avg(
            func.abs(
                model.expected_power_generation_megawatts - GSPYieldSQL.solar_generation_kw / 1000
            )
        ),
        func.count(model.expected_power_generation_megawatts),
    )
    return query


def make_mae(
    session: Session,
    datetime_interval: DatetimeInterval,
    n_gsps: Optional[int] = N_GSP,
    max_forecast_horizon_minutes: Optional[int] = 480,
):
    """
    Calculate MAE for all GSPs

    :param session: database session
    :param datetime_interval: datetime interval
    :param n_gsps: The number of Gsps to loop over. Default is N_GSP. (+1 for national)
    :param: max_forecast_horizon_minutes.
        The maximum forecast horizon we should look at, default is 8 hours
    """

    for gps_id in range(0, n_gsps + 1):
        make_mae_one_gsp(session=session, datetime_interval=datetime_interval, gsp_id=gps_id)

    make_mae_all_gsp(session=session, datetime_interval=datetime_interval)

    # loop over forecast horizons
    for forecast_horizon_minutes in range(0, max_forecast_horizon_minutes, 30):
        make_mae_one_gsp_with_forecast_horizon(
            session=session,
            datetime_interval=datetime_interval,
            gsp_id=0,
            forecast_horizon_minutes=forecast_horizon_minutes,
        )

    for gps_id in range(0, n_gsps + 1):
        make_pvlive_mae(session=session, datetime_interval=datetime_interval, gsp_id=gps_id)
