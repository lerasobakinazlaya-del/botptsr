param(
    [string]$OutputDir = "assets\stories",
    [string]$BackgroundDir = "assets\story-backgrounds"
)

Add-Type -AssemblyName System.Drawing

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function New-RoundedRectanglePath {
    param(
        [float]$X,
        [float]$Y,
        [float]$Width,
        [float]$Height,
        [float]$Radius
    )

    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $diameter = $Radius * 2
    $path.AddArc($X, $Y, $diameter, $diameter, 180, 90)
    $path.AddArc($X + $Width - $diameter, $Y, $diameter, $diameter, 270, 90)
    $path.AddArc($X + $Width - $diameter, $Y + $Height - $diameter, $diameter, $diameter, 0, 90)
    $path.AddArc($X, $Y + $Height - $diameter, $diameter, $diameter, 90, 90)
    $path.CloseFigure()
    return $path
}

function Draw-StoryFrame {
    param(
        [string]$BackgroundPath,
        [string]$OutputPath,
        [string]$BubbleText,
        [int]$ActiveSegment = 0
    )

    $width = 1080
    $height = 1920
    $bitmap = New-Object System.Drawing.Bitmap($width, $height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)

    $background = [System.Drawing.Image]::FromFile((Resolve-Path -LiteralPath $BackgroundPath))
    try {
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit

        $targetRatio = $width / $height
        $sourceRatio = $background.Width / $background.Height
        if ($sourceRatio -gt $targetRatio) {
            $cropHeight = $background.Height
            $cropWidth = [int]($cropHeight * $targetRatio)
            $cropX = [int](($background.Width - $cropWidth) / 2)
            $cropY = 0
        } else {
            $cropWidth = $background.Width
            $cropHeight = [int]($cropWidth / $targetRatio)
            $cropX = 0
            $cropY = [int](($background.Height - $cropHeight) / 2)
        }

        $sourceRect = New-Object System.Drawing.Rectangle($cropX, $cropY, $cropWidth, $cropHeight)
        $targetRect = New-Object System.Drawing.Rectangle(0, 0, $width, $height)
        $graphics.DrawImage($background, $targetRect, $sourceRect, [System.Drawing.GraphicsUnit]::Pixel)

        $graphics.FillRectangle((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(78, 0, 7, 10))), 0, 0, $width, $height)
        $graphics.FillRectangle((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(42, 0, 0, 0))), 0, 0, $width, 260)
        $graphics.FillRectangle((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(38, 0, 0, 0))), 0, 1510, $width, 410)

        $white = [System.Drawing.Color]::FromArgb(245, 255, 255, 255)
        $muted = [System.Drawing.Color]::FromArgb(178, 255, 255, 255)
        $teal = [System.Drawing.Color]::FromArgb(255, 58, 214, 178)
        $track = [System.Drawing.Color]::FromArgb(118, 255, 255, 255)

        $segmentCount = 7
        $gap = 8
        $barX = 36
        $barY = 38
        $barH = 6
        $barW = [math]::Floor(($width - ($barX * 2) - ($gap * ($segmentCount - 1))) / $segmentCount)
        for ($i = 0; $i -lt $segmentCount; $i++) {
            $x = $barX + ($i * ($barW + $gap))
            $path = New-RoundedRectanglePath $x $barY $barW $barH 3
            $color = if ($i -le $ActiveSegment) { $white } else { $track }
            $graphics.FillPath((New-Object System.Drawing.SolidBrush($color)), $path)
            $path.Dispose()
        }

        $avatarX = 54
        $avatarY = 90
        $avatarSize = 76
        $graphics.FillEllipse((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(150, 0, 15, 18))), $avatarX, $avatarY, $avatarSize, $avatarSize)
        $graphics.DrawEllipse((New-Object System.Drawing.Pen($teal, 3)), $avatarX, $avatarY, $avatarSize, $avatarSize)
        $graphics.DrawEllipse((New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(210, 72, 255, 221), 2)), $avatarX + 18, $avatarY + 24, 42, 24)
        $graphics.DrawArc((New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(225, 82, 245, 218), 3)), $avatarX + 18, $avatarY + 17, 44, 44, 205, 250)

        $titleFont = New-Object System.Drawing.Font("Segoe UI", 30, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)
        $statusFont = New-Object System.Drawing.Font("Segoe UI", 23, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)
        $bubbleNameFont = New-Object System.Drawing.Font("Segoe UI", 24, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)
        $bubbleFont = New-Object System.Drawing.Font("Segoe UI", 34, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)

        $graphics.DrawString("Нить", $titleFont, (New-Object System.Drawing.SolidBrush($white)), 155, 92)
        $graphics.DrawString("онлайн", $statusFont, (New-Object System.Drawing.SolidBrush($muted)), 155, 128)

        for ($i = 0; $i -lt 3; $i++) {
            $graphics.FillEllipse((New-Object System.Drawing.SolidBrush($white)), 1012, (94 + $i * 18), 8, 8)
        }

        $bubbleX = 300
        $bubbleY = 1288
        $bubbleW = 610
        $bubbleH = 184
        if ($BubbleText.Length -gt 66) {
            $bubbleX = 170
            $bubbleW = 750
            $bubbleH = 220
            $bubbleY = 1256
        }

        $bubblePath = New-RoundedRectanglePath $bubbleX $bubbleY $bubbleW $bubbleH 34
        $graphics.FillPath((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(190, 18, 37, 40))), $bubblePath)
        $bubblePath.Dispose()
        $tail = New-Object System.Drawing.Drawing2D.GraphicsPath
        [System.Drawing.PointF[]]$tailPoints = @(
            (New-Object System.Drawing.PointF -ArgumentList ($bubbleX + 28), ($bubbleY + $bubbleH - 38)),
            (New-Object System.Drawing.PointF -ArgumentList ($bubbleX - 20), ($bubbleY + $bubbleH - 8)),
            (New-Object System.Drawing.PointF -ArgumentList ($bubbleX + 48), ($bubbleY + $bubbleH - 12))
        )
        $tail.AddPolygon($tailPoints)
        $graphics.FillPath((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(190, 18, 37, 40))), $tail)
        $tail.Dispose()

        $graphics.DrawString("Нить", $bubbleNameFont, (New-Object System.Drawing.SolidBrush($teal)), $bubbleX + 34, $bubbleY + 22)
        $textRect = New-Object System.Drawing.RectangleF -ArgumentList ($bubbleX + 34), ($bubbleY + 64), ($bubbleW - 68), ($bubbleH - 82)
        $format = New-Object System.Drawing.StringFormat
        $format.LineAlignment = [System.Drawing.StringAlignment]::Near
        $format.Alignment = [System.Drawing.StringAlignment]::Near
        $graphics.DrawString($BubbleText, $bubbleFont, (New-Object System.Drawing.SolidBrush($white)), $textRect, $format)

        $bitmap.Save((Join-Path (Get-Location) $OutputPath), [System.Drawing.Imaging.ImageFormat]::Png)

        $titleFont.Dispose()
        $statusFont.Dispose()
        $bubbleNameFont.Dispose()
        $bubbleFont.Dispose()
    } finally {
        $background.Dispose()
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$stories = @(
    @{ Background = "story-bg-01.png"; Output = "pinned-post-story.png"; Text = "Ты тогда так и не рассказал, чем всё закончилось"; Segment = 0 },
    @{ Background = "story-bg-02.png"; Output = "long-task-story.png"; Text = "Большой текст можно разобрать целиком, без обрыва на первой строке"; Segment = 1 },
    @{ Background = "story-bg-03.png"; Output = "memory-story.png"; Text = "Я помню: тебя зовут Валера. Продолжим с того места?"; Segment = 2 },
    @{ Background = "story-bg-04.png"; Output = "payments-story.png"; Text = "Можно открыть день доступа и разобрать всё спокойно"; Segment = 3 },
    @{ Background = "story-bg-01.png"; Output = "product-update-story.png"; Text = "Я стал помнить контекст, принимать Stars и писать в канал"; Segment = 4 },
    @{ Background = "story-bg-02.png"; Output = "prompt-day-story.png"; Text = "Сначала поймём, что ты правда хочешь сказать"; Segment = 5 },
    @{ Background = "story-bg-03.png"; Output = "week-summary-story.png"; Text = "Главная метрика — захотелось ли ответить вторым сообщением"; Segment = 6 }
)

foreach ($story in $stories) {
    $backgroundPath = Join-Path $BackgroundDir $story.Background
    $outputPath = Join-Path $OutputDir $story.Output
    Draw-StoryFrame -BackgroundPath $backgroundPath -OutputPath $outputPath -BubbleText $story.Text -ActiveSegment $story.Segment
    Write-Host "Rendered $outputPath"
}
