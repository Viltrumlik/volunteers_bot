from aiogram import Dispatcher


def register_handlers(dp: Dispatcher) -> None:
    from app.handlers import emergency as emergency_handlers
    from app.handlers.admin import applications as admin_applications
    from app.handlers.admin import attendance as admin_attendance
    from app.handlers.admin import broadcast as admin_broadcast
    from app.handlers.admin import events as admin_events
    from app.handlers.admin import faq as admin_faq
    from app.handlers.admin import inbox as admin_inbox
    from app.handlers.admin import projects_admin as admin_projects
    from app.handlers.admin import regions as admin_regions
    from app.handlers.admin import super_admin as admin_super
    from app.handlers.user import errors as user_errors
    from app.handlers.user import group_commands as user_group
    from app.handlers.user import hours as user_hours
    from app.handlers.user import menu as user_menu
    from app.handlers.user import profile as user_profile
    from app.handlers.user import projects as user_projects
    from app.handlers.user import registration as user_registration
    from app.handlers.user import shifts as user_shifts
    from app.handlers.user import suggestion as user_suggestion
    from app.handlers.user import support as user_support

    dp.include_router(emergency_handlers.router)
    dp.include_router(user_errors.router)
    dp.include_router(admin_inbox.router)
    dp.include_router(user_group.router)
    dp.include_router(user_registration.router)
    dp.include_router(admin_faq.router)
    dp.include_router(admin_broadcast.router)
    dp.include_router(admin_applications.router)
    dp.include_router(admin_projects.router)
    dp.include_router(admin_events.router)
    dp.include_router(admin_attendance.router)
    dp.include_router(admin_super.router)
    dp.include_router(admin_regions.router)
    dp.include_router(user_support.router)
    dp.include_router(user_suggestion.router)
    dp.include_router(user_projects.router)
    dp.include_router(user_shifts.router)
    dp.include_router(user_hours.router)
    dp.include_router(user_profile.router)
    dp.include_router(user_menu.router)
