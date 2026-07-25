"""API рутер за ТРЗ (tenant-scoped)."""
import datetime as dt
import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentCompany, DbSession, require
from app.modules.payroll import service
from app.modules.payroll.schemas import (
    AbsenceCreate,
    AbsenceOut,
    ContractCreate,
    ContractOut,
    ContractTerminate,
    ContractUpdate,
    EmployeeCreate,
    EmployeeOut,
    EmployeeUpdate,
    PayrollRunOut,
    PayrollRunRequest,
    PayrollRunSummary,
    RateSetCreate,
    RateSetOut,
    RateSetUpdate,
)

router = APIRouter(prefix="/payroll", tags=["payroll"])


# ---------------------------------------------------------------- параметри
@router.post("/rate-sets", response_model=RateSetOut, status_code=status.HTTP_201_CREATED,
             dependencies=[require("payroll.manage_rates")])
def create_rate_set(data: RateSetCreate, ctx: CurrentCompany, db: DbSession) -> RateSetOut:
    return RateSetOut.model_validate(service.create_rate_set(db, ctx.company.id, data))


@router.get("/rate-sets", response_model=list[RateSetOut], dependencies=[require("payroll.view")])
def list_rate_sets(ctx: CurrentCompany, db: DbSession) -> list[RateSetOut]:
    return [RateSetOut.model_validate(r) for r in service.list_rate_sets(db, ctx.company.id)]


@router.get("/rate-sets/{rate_set_id}", response_model=RateSetOut,
            dependencies=[require("payroll.view")])
def get_rate_set(rate_set_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> RateSetOut:
    return RateSetOut.model_validate(service.get_rate_set(db, ctx.company.id, rate_set_id))


@router.patch("/rate-sets/{rate_set_id}", response_model=RateSetOut,
              dependencies=[require("payroll.manage_rates")])
def update_rate_set(
    rate_set_id: uuid.UUID, data: RateSetUpdate, ctx: CurrentCompany, db: DbSession
) -> RateSetOut:
    return RateSetOut.model_validate(
        service.update_rate_set(db, ctx.company.id, rate_set_id, data)
    )


@router.delete("/rate-sets/{rate_set_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[require("payroll.manage_rates")])
def delete_rate_set(rate_set_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> None:
    service.delete_rate_set(db, ctx.company.id, rate_set_id)


# ---------------------------------------------------------------- служители
@router.post("/employees", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED,
             dependencies=[require("payroll.manage_employees")])
def create_employee(data: EmployeeCreate, ctx: CurrentCompany, db: DbSession) -> EmployeeOut:
    return EmployeeOut.model_validate(service.create_employee(db, ctx.company.id, data))


@router.get("/employees", response_model=list[EmployeeOut], dependencies=[require("payroll.view")])
def list_employees(
    ctx: CurrentCompany, db: DbSession, active_only: bool = Query(default=False)
) -> list[EmployeeOut]:
    return [
        EmployeeOut.model_validate(e)
        for e in service.list_employees(db, ctx.company.id, active_only)
    ]


@router.get("/employees/{employee_id}", response_model=EmployeeOut,
            dependencies=[require("payroll.view")])
def get_employee(employee_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> EmployeeOut:
    return EmployeeOut.model_validate(service.get_employee(db, ctx.company.id, employee_id))


@router.patch("/employees/{employee_id}", response_model=EmployeeOut,
              dependencies=[require("payroll.manage_employees")])
def update_employee(
    employee_id: uuid.UUID, data: EmployeeUpdate, ctx: CurrentCompany, db: DbSession
) -> EmployeeOut:
    return EmployeeOut.model_validate(
        service.update_employee(db, ctx.company.id, employee_id, data)
    )


# ---------------------------------------------------------------- договори
@router.post("/contracts", response_model=ContractOut, status_code=status.HTTP_201_CREATED,
             dependencies=[require("payroll.manage_employees")])
def create_contract(data: ContractCreate, ctx: CurrentCompany, db: DbSession) -> ContractOut:
    return ContractOut.model_validate(service.create_contract(db, ctx.company.id, data))


@router.get("/contracts", response_model=list[ContractOut], dependencies=[require("payroll.view")])
def list_contracts(
    ctx: CurrentCompany, db: DbSession, employee_id: uuid.UUID | None = Query(default=None)
) -> list[ContractOut]:
    return [
        ContractOut.model_validate(c)
        for c in service.list_contracts(db, ctx.company.id, employee_id)
    ]


@router.patch("/contracts/{contract_id}", response_model=ContractOut,
              dependencies=[require("payroll.manage_employees")])
def update_contract(
    contract_id: uuid.UUID, data: ContractUpdate, ctx: CurrentCompany, db: DbSession
) -> ContractOut:
    return ContractOut.model_validate(
        service.update_contract(db, ctx.company.id, contract_id, data)
    )


@router.post("/contracts/{contract_id}/terminate", response_model=ContractOut,
             dependencies=[require("payroll.manage_employees")])
def terminate_contract(
    contract_id: uuid.UUID, data: ContractTerminate, ctx: CurrentCompany, db: DbSession
) -> ContractOut:
    return ContractOut.model_validate(
        service.terminate_contract(db, ctx.company.id, contract_id, data.termination_date)
    )


# ---------------------------------------------------------------- отсъствия
@router.post("/absences", response_model=AbsenceOut, status_code=status.HTTP_201_CREATED,
             dependencies=[require("payroll.manage_employees")])
def create_absence(data: AbsenceCreate, ctx: CurrentCompany, db: DbSession) -> AbsenceOut:
    return AbsenceOut.model_validate(service.create_absence(db, ctx.company.id, data))


@router.get("/absences", response_model=list[AbsenceOut], dependencies=[require("payroll.view")])
def list_absences(
    ctx: CurrentCompany,
    db: DbSession,
    contract_id: uuid.UUID | None = Query(default=None),
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
) -> list[AbsenceOut]:
    return [
        AbsenceOut.model_validate(a)
        for a in service.list_absences(db, ctx.company.id, contract_id, date_from, date_to)
    ]


@router.delete("/absences/{absence_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[require("payroll.manage_employees")])
def delete_absence(absence_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> None:
    service.delete_absence(db, ctx.company.id, absence_id)


# ---------------------------------------------------------------- ведомост
@router.get("/runs", response_model=list[PayrollRunSummary], dependencies=[require("payroll.view")])
def list_runs(ctx: CurrentCompany, db: DbSession) -> list[PayrollRunSummary]:
    return [PayrollRunSummary.model_validate(r) for r in service.list_runs(db, ctx.company.id)]


@router.post("/runs/calculate", response_model=PayrollRunOut,
             dependencies=[require("payroll.calculate")])
def calculate_run(data: PayrollRunRequest, ctx: CurrentCompany, db: DbSession) -> PayrollRunOut:
    """Изчислява ведомостта за месеца. Системата предлага — одобряването е отделна стъпка."""
    return PayrollRunOut.model_validate(
        service.calculate_run(db, ctx.company.id, data.year, data.month)
    )


@router.get("/runs/{run_id}", response_model=PayrollRunOut, dependencies=[require("payroll.view")])
def get_run(run_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> PayrollRunOut:
    return PayrollRunOut.model_validate(service.get_run(db, ctx.company.id, run_id))


@router.post("/runs/{run_id}/approve", response_model=PayrollRunOut,
             dependencies=[require("payroll.approve")])
def approve_run(run_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> PayrollRunOut:
    return PayrollRunOut.model_validate(
        service.approve_run(db, ctx.company.id, run_id, ctx.membership.user_id)
    )


@router.post("/runs/{run_id}/post", response_model=PayrollRunOut,
             dependencies=[require("payroll.approve")])
def post_run(run_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> PayrollRunOut:
    return PayrollRunOut.model_validate(
        service.post_run(db, ctx.company, run_id, ctx.membership.user_id)
    )


@router.post("/runs/{run_id}/cancel", response_model=PayrollRunOut,
             dependencies=[require("payroll.approve")])
def cancel_run(run_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> PayrollRunOut:
    return PayrollRunOut.model_validate(service.cancel_run(db, ctx.company.id, run_id))
