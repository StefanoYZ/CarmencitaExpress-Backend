from app.modules.load_optimization.algorithms.worst_fit import (
    worst_fit_algorithm
)
from app.modules.load_optimization.models.package import Package
from app.modules.load_optimization.models.truck import Truck
from app.modules.load_optimization.algorithms.best_fit_decreasing_3d import (
    best_fit_decreasing_3d_algorithm
)
from app.modules.load_optimization.algorithms.backtracking_3d import (
    backtracking_3d_algorithm
)


class LoadOptimizationService:

    @staticmethod
    def build_truck(request):
        return Truck(
            width=request.truck.width,
            height=request.truck.height,
            length=request.truck.length,
            max_weight=request.truck.max_weight
        )

    @staticmethod
    def build_packages(request):
        return [
            Package(
                id=p.id,
                width=p.width,
                height=p.height,
                length=p.length,
                weight=p.weight,
                fragility=p.fragility,
                destination=p.destination,
                content_type=p.content_type
            )
            for p in request.packages
        ]

    @staticmethod
    def get_route(request):
        return getattr(
            request,
            "route",
            "TRUJILLO_OROCULLAY"
        )

    @staticmethod
    def get_origin_agency(request):
        return getattr(
            request,
            "origin_agency",
            "TRUJILLO"
        )

    @staticmethod
    def build_skipped_backtracking_result(packages):
        return {
            "algorithm": "backtracking_logistic",
            "occupation_percentage": 0,
            "weight_percentage": 0,
            "success_rate": 0,
            "execution_time_ms": 0,
            "placed_count": 0,
            "unplaced_count": len(packages),
            "zone_compliance_percentage": None,
            "stacking_compliance_percentage": None,
            "stability_compliance_percentage": None,
            "placed_packages": [],
            "unplaced_packages": [
                {
                    "id": package.id,
                    "reason_code": "ALGORITHM_LIMIT",
                    "reason": (
                        "Cantidad de paquetes excede el límite recomendado "
                        "para Backtracking"
                    )
                }
                for package in packages
            ],
            "message": (
                "Backtracking omitido porque el escenario supera el límite "
                "recomendado de paquetes"
            )
        }

    @staticmethod
    def build_comparison_row(algorithm_name: str, result: dict) -> dict:
        return {
            "algorithm": algorithm_name,
            "occupation_percentage": result.get(
                "occupation_percentage",
                result.get("space_utilization", 0)
            ),
            "weight_percentage": result.get(
                "weight_percentage",
                result.get("weight_utilization", 0)
            ),
            "success_rate": result.get(
                "success_rate",
                0
            ),
            "execution_time_ms": result.get(
                "execution_time_ms",
                0
            ),
            "placed_count": result.get(
                "placed_count",
                len(result.get("placed_packages", []))
            ),
            "unplaced_count": result.get(
                "unplaced_count",
                len(result.get("unplaced_packages", []))
            ),
            "zone_compliance_percentage": result.get(
                "zone_compliance_percentage",
                None
            ),
            "stacking_compliance_percentage": result.get(
                "stacking_compliance_percentage",
                None
            ),
            "stability_compliance_percentage": result.get(
                "stability_compliance_percentage",
                None
            ),
            "message": result.get(
                "message",
                None
            )
        }

    @staticmethod
    def optimize(request):

        truck = LoadOptimizationService.build_truck(request)
        packages = LoadOptimizationService.build_packages(request)

        algorithm = request.algorithm.lower()
        route = LoadOptimizationService.get_route(request)
        origin_agency = LoadOptimizationService.get_origin_agency(request)

        if algorithm == "worst_fit":
            return worst_fit_algorithm(
                truck,
                packages
            )

        if algorithm == "bfd3d":
            return best_fit_decreasing_3d_algorithm(
                truck,
                packages,
                route=route,
                origin_agency=origin_agency
            )

        if algorithm == "backtracking":
            if len(packages) > 8:
                return LoadOptimizationService.build_skipped_backtracking_result(
                    packages
                )

            return backtracking_3d_algorithm(
                truck,
                packages,
                route=route,
                origin_agency=origin_agency
            )

        raise ValueError(
            f"Algoritmo no soportado: {request.algorithm}"
        )

    @staticmethod
    def compare(request):

        truck = LoadOptimizationService.build_truck(request)
        packages = LoadOptimizationService.build_packages(request)

        route = LoadOptimizationService.get_route(request)
        origin_agency = LoadOptimizationService.get_origin_agency(request)

        worst_fit_result = worst_fit_algorithm(
            truck,
            packages
        )

        bfd3d_result = best_fit_decreasing_3d_algorithm(
            truck,
            packages,
            route=route,
            origin_agency=origin_agency
        )

        if len(packages) > 8:
            backtracking_result = (
                LoadOptimizationService.build_skipped_backtracking_result(
                    packages
                )
            )
        else:
            backtracking_result = backtracking_3d_algorithm(
                truck,
                packages,
                route=route,
                origin_agency=origin_agency
            )

        results = {
            "worst_fit": worst_fit_result,
            "bfd3d": bfd3d_result,
            "backtracking": backtracking_result
        }

        comparison_table = [
            LoadOptimizationService.build_comparison_row(
                "worst_fit",
                worst_fit_result
            ),
            LoadOptimizationService.build_comparison_row(
                "bfd3d",
                bfd3d_result
            ),
            LoadOptimizationService.build_comparison_row(
                "backtracking",
                backtracking_result
            )
        ]

        return {
            "route": route,
            "origin_agency": origin_agency,
            "algorithms_compared": [
                "worst_fit",
                "bfd3d",
                "backtracking"
            ],
            "comparison_table": comparison_table,
            "results": results
        }