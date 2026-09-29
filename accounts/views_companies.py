"""Panel de empresas (tenants) — solo superuser, fuera de cualquier prefijo: /empresas/."""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import CompanyForm
from .models import Company, Profile
from .services import (
    MembershipError, add_extra_membership, copy_role_matrix, ensure_company_configs,
    remove_extra_membership,
)
from .views import _superuser_required

User = get_user_model()


@_superuser_required
def company_list(request):
    companies = Company.objects.annotate(
        num_users=Count('profiles', distinct=True),
        num_extra_users=Count('extra_member_profiles', distinct=True),
        num_tickets=Count('tickets', distinct=True),
    ).order_by('-is_active', 'name')
    return render(request, 'accounts/companies/list.html', {'companies': companies})


@_superuser_required
def company_create(request):
    templates = Company.objects.filter(is_active=True).order_by('name')
    form = CompanyForm()
    if request.method == 'POST':
        form = CompanyForm(request.POST, request.FILES)
        if form.is_valid():
            template = templates.filter(pk=request.POST.get('template') or None).first()
            with transaction.atomic():
                company = form.save()
                # Matriz de roles: copia de otra empresa (con los ajustes que ya le hizo
                # el superuser) o los defaults de código; más las configs vacías.
                copy_role_matrix(company, template)
                ensure_company_configs(company)
            messages.success(
                request,
                f'Empresa «{company.name}» creada. Entrá a /{company.slug}/acceso/admin/ para invitar '
                'al primer coordinador.',
            )
            return redirect('companies:list')
        messages.error(request, 'Revisá los datos de la empresa.')
    return render(request, 'accounts/companies/form.html', {
        'form': form, 'company': None, 'templates': templates,
    })


@_superuser_required
def company_edit(request, slug):
    company = get_object_or_404(Company, slug=slug)
    form = CompanyForm(instance=company)
    if request.method == 'POST':
        form = CompanyForm(request.POST, request.FILES, instance=company)
        if form.is_valid():
            company = form.save()
            messages.success(request, f'Empresa «{company.name}» actualizada.')
            return redirect('companies:edit', slug=company.slug)
        messages.error(request, 'Revisá los datos de la empresa.')
    # Usuarios de OTRAS empresas que también operan en esta (Profile.extra_companies).
    extra_members = (
        Profile.objects.filter(extra_companies=company)
        .select_related('user', 'company').order_by('user__email')
    )
    return render(request, 'accounts/companies/form.html', {
        'form': form, 'company': company, 'templates': None, 'extra_members': extra_members,
    })


# ── Miembros adicionales (usuarios de otra empresa con acceso a esta) ─────────

@_superuser_required
@require_POST
def company_member_add(request, slug):
    company = get_object_or_404(Company, slug=slug)
    email = (request.POST.get('email') or '').strip()
    user = User.objects.filter(email__iexact=email).first() if email else None
    if user is None:
        messages.error(request, f'No existe ninguna cuenta con el correo «{email}». '
                                'Las cuentas nuevas se invitan desde Cuentas, dentro de su empresa.')
    else:
        try:
            add_extra_membership(user, company)
        except MembershipError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f'{user.email} ahora también opera en «{company.name}» '
                                      f'({user.profile.get_role_display()}).')
    return redirect('companies:edit', slug=company.slug)


@_superuser_required
@require_POST
def company_member_remove(request, slug, pk):
    company = get_object_or_404(Company, slug=slug)
    user = get_object_or_404(User, pk=pk, profile__extra_companies=company)
    try:
        remove_extra_membership(user, company)
    except MembershipError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f'{user.email} ya no tiene acceso a «{company.name}».')
    return redirect('companies:edit', slug=company.slug)
