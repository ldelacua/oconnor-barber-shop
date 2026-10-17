from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class TasaBCV(models.Model):
    fecha = models.DateField(
        unique=True,
        default=timezone.localdate,
        verbose_name="Fecha",
    )
    tasa_bcv = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.000001"))],
        verbose_name="Tasa BCV (Bs. por 1 USD)",
        help_text="Introduce cuántos bolívares equivalen a un dólar estadounidense.",
    )

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Tasa BCV"
        verbose_name_plural = "Tasas BCV"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(tasa_bcv__gt=0),
                name="tasa_bcv_positiva",
            ),
        ]

    def __str__(self):
        return f"{self.fecha:%d/%m/%Y}: {self.tasa_bcv} Bs./USD"
