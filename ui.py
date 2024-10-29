import csv
import statistics
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Set

from PyQt5.QtChart import QChart, QChartView, QLineSeries, QScatterSeries, QValueAxis
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush, QColor, QPen
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)


@dataclass
class GlucoseData:
    glucose_values: List[int]
    dates: Set[date]
    high_glucose_count: int
    high_glucose_periods: int


class CGMParser(ABC):
    @abstractmethod
    def parse(self, file_path: str) -> GlucoseData:
        pass


class LibreParser(CGMParser):
    def parse(self, file_path: str) -> GlucoseData:
        glucose_values = []
        dates = set()
        high_glucose_count = 0
        high_glucose_periods = 0
        in_high_glucose_period = False
        last_high_glucose_time = None

        skip = True
        header = None

        with open(file_path, newline="") as csvfile:
            for row in csv.reader(csvfile):
                if row[0] == "Device":
                    skip = False
                    header = row
                elif not skip:
                    data_dict = {header[i]: row[i] for i in range(len(header))}

                    if data_dict.get("Record Type", None) != "0":
                        continue

                    historic_glucose_value = data_dict.get(
                        "Historic Glucose mg/dL", None
                    )
                    scan_glucose_value = data_dict.get("Scan Glucose mg/dL", None)
                    glucose_value = historic_glucose_value or scan_glucose_value
                    try:
                        glucose_value_int = int(glucose_value)
                        glucose_values.append(glucose_value_int)

                        try:
                            current_time = datetime.strptime(
                                data_dict["Device Timestamp"], "%m-%d-%Y %I:%M %p"
                            )
                        except ValueError:
                            try:
                                current_time = datetime.strptime(
                                    data_dict["Device Timestamp"], "%m/%d/%Y %H:%M"
                                )
                            except ValueError:
                                try:
                                    current_time = datetime.strptime(
                                        data_dict["Device Timestamp"], "%m/%d/%y %H:%M"
                                    )
                                except ValueError as e:
                                    print(
                                        f"Could not parse timestamp '{data_dict['Device Timestamp']}': {e}"
                                    )
                                    continue

                        dates.add(current_time.date())

                        if glucose_value_int >= 140:
                            high_glucose_count += 1
                            if not in_high_glucose_period or (
                                last_high_glucose_time
                                and current_time - last_high_glucose_time
                                >= timedelta(hours=1)
                            ):
                                high_glucose_periods += 1
                                in_high_glucose_period = True
                            last_high_glucose_time = current_time
                        else:
                            in_high_glucose_period = False

                    except (ValueError, TypeError) as e:
                        print(f"Error processing row: {e}. Skipping this row.")
                        continue

        return GlucoseData(
            glucose_values=glucose_values,
            dates=dates,
            high_glucose_count=high_glucose_count,
            high_glucose_periods=high_glucose_periods,
        )


class DexcomParser(CGMParser):
    def parse(self, file_path: str) -> GlucoseData:
        glucose_values = []
        dates = set()
        high_glucose_count = 0
        high_glucose_periods = 0
        in_high_glucose_period = False
        last_high_glucose_time = None

        with open(file_path, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if row["Event Type"] != "EGV":
                    continue

                glucose_value = row["Glucose Value (mg/dL)"]
                try:
                    glucose_value_int = int(glucose_value)
                    glucose_values.append(glucose_value_int)

                    current_time = datetime.fromisoformat(
                        row["Timestamp (YYYY-MM-DDThh:mm:ss)"]
                    )
                    dates.add(current_time.date())

                    if glucose_value_int >= 140:
                        high_glucose_count += 1
                        if not in_high_glucose_period or (
                            last_high_glucose_time
                            and current_time - last_high_glucose_time
                            >= timedelta(hours=1)
                        ):
                            high_glucose_periods += 1
                            in_high_glucose_period = True
                        last_high_glucose_time = current_time
                    else:
                        in_high_glucose_period = False

                except ValueError as e:
                    print(f"Error processing row: {e}. Skipping this row.")
                    continue

        return GlucoseData(
            glucose_values=glucose_values,
            dates=dates,
            high_glucose_count=high_glucose_count,
            high_glucose_periods=high_glucose_periods,
        )


class CGMAnalyzer(QWidget):
    def __init__(self):
        super().__init__()
        self.file_path = None
        self.parsers = {
            "libre": LibreParser(),
            "dexcom": DexcomParser(),
            # Add more parsers here as needed
        }
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("CGM Analyzer")
        self.resize(800, 600)

        layout = QVBoxLayout()

        self.select_file_button = QPushButton("Select CSV File")
        self.select_file_button.clicked.connect(self.select_file)
        layout.addWidget(self.select_file_button)

        layout.addWidget(QLabel("CGM Type:"))
        self.libre_toggle = QRadioButton("Freestyle Libre")
        self.dexcom_toggle = QRadioButton("Dexcom")
        self.levels_toggle = QRadioButton("Levels")
        layout.addWidget(self.libre_toggle)
        layout.addWidget(self.dexcom_toggle)
        layout.addWidget(self.levels_toggle)

        self.analyze_button = QPushButton("Analyze")
        self.analyze_button.clicked.connect(self.analyze_data)
        layout.addWidget(self.analyze_button)

        self.chart_view = QChartView()
        layout.addWidget(self.chart_view)

        self.result_label = QLabel()
        layout.addWidget(self.result_label)

        self.setLayout(layout)

    def select_file(self):
        options = QFileDialog.Options()
        self.file_path, _ = QFileDialog.getOpenFileName(
            self, "Select CSV File", "", "CSV Files (*.csv)", options=options
        )

    def get_active_parser(self) -> Optional[CGMParser]:
        if self.dexcom_toggle.isChecked():
            return self.parsers["dexcom"]
        elif self.libre_toggle.isChecked():
            return self.parsers["libre"]
        return None

    def analyze_data(self):
        if not self.file_path:
            return

        parser = self.get_active_parser()
        if not parser:
            print("Please select a CGM type")
            return

        try:
            glucose_data = parser.parse(self.file_path)
            metrics = self.calculate_metrics(glucose_data)
            self.plot_data(glucose_data, metrics)
            self.display_results(metrics)
        except Exception as e:
            print(f"Error analyzing data: {e}")

    def calculate_metrics(self, data: GlucoseData) -> Dict:
        if not data.glucose_values:
            return {}

        total_glucose = sum(data.glucose_values)
        count = len(data.glucose_values)
        average_glucose = round(total_glucose / count, 1) if count > 0 else 0
        glucose_std_dev = (
            round(statistics.stdev(data.glucose_values), 1) if count > 1 else 0
        )

        total_days = len(data.dates)
        average_spike_periods_per_day = round(
            data.high_glucose_periods / total_days if total_days else 0, 2
        )

        grade = self.calculate_grade(
            average_glucose, glucose_std_dev, average_spike_periods_per_day
        )

        return {
            "average_glucose": average_glucose,
            "glucose_std_dev": glucose_std_dev,
            "high_glucose_count": data.high_glucose_count,
            "average_spike_periods_per_day": average_spike_periods_per_day,
            "grade": grade,
        }

    def calculate_grade(
        self, avg_glucose: float, std_dev: float, spikes_per_day: float
    ) -> str:
        grade_tot = 0

        if avg_glucose < 100:
            grade_tot += 4
        elif avg_glucose < 110:
            grade_tot += 3
        elif avg_glucose >= 110:
            grade_tot += 2

        if std_dev < 15:
            grade_tot += 4
        elif std_dev < 20:
            grade_tot += 3
        elif std_dev >= 20:
            grade_tot += 2

        if spikes_per_day < 1:
            grade_tot += 4
        elif spikes_per_day < 2:
            grade_tot += 3
        elif spikes_per_day >= 2:
            grade_tot += 2

        if grade_tot >= 12:
            return "A"
        elif grade_tot >= 11:
            return "B+"
        elif grade_tot >= 9:
            return "B"
        elif grade_tot >= 8:
            return "B-"
        else:
            return "C"

    def plot_data(
        self,
        data: GlucoseData,
        metrics: Dict,
    ):
        series = QLineSeries()
        for i, g in enumerate(data.glucose_values):
            series.append(i, g)

        chart = QChart()
        chart.addSeries(series)
        chart.legend().hide()

        axisX = QValueAxis()
        axisX.setTitleText("Time")
        min_time = 0
        max_time = len(data.glucose_values) - 1
        axisX.setRange(min_time, max_time)
        chart.addAxis(axisX, Qt.AlignBottom)
        series.attachAxis(axisX)

        axisY = QValueAxis()
        axisY.setTitleText("Blood Glucose (mg/dL)")
        min_glucose = min(data.glucose_values)
        max_glucose = max(data.glucose_values)
        axisY.setRange(min_glucose - 10, max_glucose + 10)
        chart.addAxis(axisY, Qt.AlignLeft)
        series.attachAxis(axisY)

        avg_series = QLineSeries()
        avg_series.append(min_time, metrics["average_glucose"])
        avg_series.append(max_time, metrics["average_glucose"])
        avg_series.setPen(QPen(QColor("red"), 2, Qt.DotLine))
        chart.addSeries(avg_series)
        avg_series.attachAxis(axisX)
        avg_series.attachAxis(axisY)

        std_upper_series = QLineSeries()
        std_upper_series.append(
            min_time, metrics["average_glucose"] + metrics["glucose_std_dev"] / 2
        )
        std_upper_series.append(
            max_time, metrics["average_glucose"] + metrics["glucose_std_dev"] / 2
        )
        std_upper_series.setPen(QPen(QColor("black"), 1, Qt.DotLine))
        chart.addSeries(std_upper_series)
        std_upper_series.attachAxis(axisX)
        std_upper_series.attachAxis(axisY)

        std_lower_series = QLineSeries()
        std_lower_series.append(
            min_time, metrics["average_glucose"] - metrics["glucose_std_dev"]
        )
        std_lower_series.append(
            max_time, metrics["average_glucose"] - metrics["glucose_std_dev"]
        )
        std_lower_series.setPen(QPen(QColor("black"), 1, Qt.DotLine))
        chart.addSeries(std_lower_series)
        std_lower_series.attachAxis(axisX)
        std_lower_series.attachAxis(axisY)

        spike_series = QScatterSeries()
        for i, g in enumerate(data.glucose_values):
            if g >= 140:
                spike_series.append(i, g)
        spike_series.setMarkerShape(QScatterSeries.MarkerShapeCircle)
        spike_series.setMarkerSize(8.0)
        spike_series.setBrush(QBrush(QColor("black")))
        chart.addSeries(spike_series)
        spike_series.attachAxis(axisX)
        spike_series.attachAxis(axisY)

        self.chart_view.setChart(chart)

    def display_results(
        self,
        metrics: Dict,
    ):
        result_text = f"CGM Average: {metrics['average_glucose']:.2f} mg/dL\n"
        result_text += (
            f"CGM Standard Deviation: {metrics['glucose_std_dev']:.2f} mg/dL\n"
        )
        result_text += f"CGM Spikes: {metrics['high_glucose_count']}\n"
        result_text += (
            f"CGM Spikes per Day: {metrics['average_spike_periods_per_day']:.2f}\n"
        )
        result_text += f"Grade: {metrics['grade']}"
        self.result_label.setText(result_text)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    analyzer = CGMAnalyzer()
    analyzer.show()
    sys.exit(app.exec_())
