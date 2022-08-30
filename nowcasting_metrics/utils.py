""" General util functions """
from typing import Optional
from nowcasting_datamodel.models.gsp import LocationSQL
from nowcasting_datamodel.models.metric import DatetimeInterval, Metric, MetricValueSQL
from nowcasting_datamodel.read.read_metric import get_datetime_interval, get_metric


def save_metric_value_to_database(
    session,
    value: float,
    number_of_data_points: int,
    metric: Metric,
    datetime_interval: DatetimeInterval,
    location: Optional[LocationSQL],
):
    """
    Save one metric value to the database

    :param session:
    :param value:
    :param number_of_data_points:
    :param metric:
    :param datetime_interval:
    :return:
    """

    metric_sql = get_metric(session=session, name=metric.name)
    datetime_interval_sql = get_datetime_interval(
        session=session,
        start_datetime_utc=datetime_interval.start_datetime_utc,
        end_datetime_utc=datetime_interval.end_datetime_utc,
    )

    metric_value_sql = MetricValueSQL(
        value=value,
        number_of_data_points=number_of_data_points,
        metric=metric_sql,
        datetime_interval=datetime_interval_sql,
    )
    if location is not None:
        metric_value_sql.location = location

    session.add(metric_value_sql)
